"""Privacy-minimal LangChain/LangGraph callback export to Sentinel evidence."""
import hashlib
import re
from datetime import datetime, timezone
from threading import RLock
from time import monotonic

from langchain_core.callbacks import BaseCallbackHandler

from ..external_traces import ExternalTraceCreate


def _slug(value, fallback):
    text = re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')
    return (text or fallback)[:60]


def _component_name(serialized, fallback):
    if isinstance(serialized, dict):
        if serialized.get('name'):
            return serialized['name']
        identity = serialized.get('id')
        if isinstance(identity, list) and identity:
            return identity[-1]
    return fallback


def _token_pair(response):
    """Read aggregate usage metadata without retaining any generated content."""
    llm_output = getattr(response, 'llm_output', None)
    candidates = []
    if isinstance(llm_output, dict):
        candidates.extend((llm_output.get('token_usage'), llm_output.get('usage')))
    for generations in getattr(response, 'generations', ()) or ():
        for generation in generations:
            message = getattr(generation, 'message', None)
            candidates.append(getattr(message, 'usage_metadata', None))
    for usage in candidates:
        if not isinstance(usage, dict):
            continue
        input_tokens = usage.get('input_tokens', usage.get('prompt_tokens'))
        output_tokens = usage.get('output_tokens', usage.get('completion_tokens'))
        if (type(input_tokens) is int and type(output_tokens) is int and
                0 <= input_tokens <= 10000000 and 0 <= output_tokens <= 10000000):
            return input_tokens, output_tokens
    return None


class SentinelLangChainCallback(BaseCallbackHandler):
    """Capture bounded structural callbacks; never capture inputs or outputs."""

    run_inline = True
    raise_error = False

    def __init__(self, source='langchain'):
        self.source = source
        self.started_at = datetime.now(timezone.utc)
        self._start = monotonic()
        self._active = {}
        self._spans = []
        self._finished = False
        self._overflow = False
        self._lock = RLock()

    def _offset(self):
        return int((monotonic() - self._start) * 1000)

    @staticmethod
    def _id(run_id):
        return hashlib.sha256(str(run_id).encode('utf-8')).hexdigest()[:32]

    def _begin(self, run_id, parent_run_id, name, kind):
        with self._lock:
            if self._finished or run_id in self._active:
                return
            if len(self._active) + len(self._spans) >= 100:
                self._overflow = True
                return
            parent_id = self._id(parent_run_id) if parent_run_id is not None else None
            known = {item['span_id'] for item in self._active.values()} | {
                item['span_id'] for item in self._spans}
            self._active[run_id] = {'span_id': self._id(run_id),
                'parent_id': parent_id if parent_id in known else None,
                'name': name, 'kind': kind, 'status': 'completed',
                'start_offset_ms': self._offset(), 'duration_ms': 0,
                'input_tokens': None, 'output_tokens': None}

    def _end(self, run_id, *, failed=False, usage=None):
        with self._lock:
            item = self._active.pop(run_id, None)
            if item is None:
                return
            item['duration_ms'] = self._offset() - item['start_offset_ms']
            if failed:
                item['status'] = 'failed'
            if usage is not None and item['kind'] == 'model':
                item['input_tokens'], item['output_tokens'] = usage
            self._spans.append(item)

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        component = _component_name(serialized, kwargs.get('name') or 'run')
        self._begin(run_id, parent_run_id, 'agent.' + _slug(component, 'run'), 'agent')

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._end(run_id)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._end(run_id, failed=True)

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        component = _component_name(serialized, 'generate')
        self._begin(run_id, parent_run_id, 'model.' + _slug(component, 'generate'), 'model')

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self.on_llm_start(serialized, (), run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._end(run_id, usage=_token_pair(response))

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, failed=True)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        component = _component_name(serialized, kwargs.get('name') or 'call')
        self._begin(run_id, parent_run_id, 'tool.' + _slug(component, 'call'), 'tool')

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, failed=True)

    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None, **kwargs):
        component = _component_name(serialized, kwargs.get('name') or 'search')
        self._begin(run_id, parent_run_id, 'retrieval.' + _slug(component, 'search'), 'retrieval')

    def on_retriever_end(self, documents, *, run_id, **kwargs):
        self._end(run_id)

    def on_retriever_error(self, error, *, run_id, **kwargs):
        self._end(run_id, failed=True)

    def finish(self, output, *, reported_status='succeeded', idempotency_key=None):
        with self._lock:
            if self._finished:
                raise ValueError('This trace is already finalized.')
            if self._active:
                raise ValueError('Finalize only after all framework callbacks have closed.')
            if self._overflow:
                raise ValueError('Trace exceeds the 100-span evidence limit.')
            body = ExternalTraceCreate.model_validate({'schema_version': 1,
                'source': self.source,
                'idempotency_key': idempotency_key or 'trace-' + hashlib.sha256(
                    f'{self.started_at.isoformat()}:{id(self)}'.encode()).hexdigest()[:32],
                'started_at': self.started_at, 'duration_ms': self._offset(),
                'reported_status': reported_status, 'spans': self._spans,
                'output': output})
            self._finished = True
            return body.model_dump(mode='json')
