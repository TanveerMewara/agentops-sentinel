import unittest
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError
from langgraph.graph import END, START, StateGraph

from sentinel.integrations.langchain_trace import SentinelLangChainCallback


class LangChainTraceTests(unittest.TestCase):
    def test_real_langgraph_invoke_exports_nested_trace(self):
        builder = StateGraph(dict)
        builder.add_node('increment', lambda state: {'value': state.get('value', 0) + 1})
        builder.add_edge(START, 'increment')
        builder.add_edge('increment', END)
        graph = builder.compile()
        callback = SentinelLangChainCallback(source='langgraph')
        output = graph.invoke({'value': 1}, config={'callbacks': [callback]})
        evidence = callback.finish(output, idempotency_key='langgraph-integration-trace')
        self.assertEqual(output, {'value': 2})
        self.assertEqual([span['name'] for span in evidence['spans']],
            ['agent.increment', 'agent.langgraph'])
        self.assertIsNotNone(evidence['spans'][0]['parent_id'])
        self.assertIsNone(evidence['spans'][1]['parent_id'])

    def test_callbacks_capture_structure_usage_and_no_payloads(self):
        callback = SentinelLangChainCallback()
        root, retrieval, model, tool = uuid4(), uuid4(), uuid4(), uuid4()
        callback.on_chain_start({'name': 'Support Graph'}, {'private': 'INPUT-SECRET'}, run_id=root)
        callback.on_retriever_start({'name': 'Customer Context'}, 'QUERY-SECRET',
            run_id=retrieval, parent_run_id=root)
        callback.on_retriever_end([{'private': 'DOCUMENT-SECRET'}], run_id=retrieval)
        callback.on_chat_model_start({'id': ['provider', 'GPT Test']}, [['PROMPT-SECRET']],
            run_id=model, parent_run_id=root)
        response = SimpleNamespace(llm_output={'token_usage': {
            'prompt_tokens': 12, 'completion_tokens': 4}}, generations=[])
        callback.on_llm_end(response, run_id=model)
        callback.on_tool_start({'name': 'Send Reply'}, 'ARGUMENT-SECRET',
            run_id=tool, parent_run_id=root)
        callback.on_tool_end('RESULT-SECRET', run_id=tool)
        callback.on_chain_end({'private': 'OUTPUT-SECRET'}, run_id=root)
        evidence = callback.finish({'result': 'sanitized'}, idempotency_key='stable-trace-key')
        self.assertEqual([span['kind'] for span in evidence['spans']],
            ['retrieval', 'model', 'tool', 'agent'])
        self.assertEqual([span['name'] for span in evidence['spans']],
            ['retrieval.customer-context', 'model.gpt-test', 'tool.send-reply',
             'agent.support-graph'])
        model_span = next(span for span in evidence['spans'] if span['kind'] == 'model')
        self.assertEqual((model_span['input_tokens'], model_span['output_tokens']), (12, 4))
        serialized = str(evidence)
        for secret in ('INPUT-SECRET', 'QUERY-SECRET', 'DOCUMENT-SECRET',
                       'PROMPT-SECRET', 'ARGUMENT-SECRET', 'RESULT-SECRET', 'OUTPUT-SECRET'):
            self.assertNotIn(secret, serialized)

    def test_errors_are_status_only_and_missing_usage_stays_unknown(self):
        callback = SentinelLangChainCallback(source='langgraph')
        root, model = uuid4(), uuid4()
        callback.on_chain_start({}, {}, run_id=root)
        callback.on_llm_start({}, ['PRIVATE'], run_id=model, parent_run_id=root)
        callback.on_llm_error(RuntimeError('PRIVATE-ERROR'), run_id=model)
        callback.on_chain_error(RuntimeError('PRIVATE-ROOT-ERROR'), run_id=root)
        evidence = callback.finish({'error': 'sanitized'}, reported_status='failed')
        self.assertTrue(all(span['status'] == 'failed' for span in evidence['spans']))
        self.assertIsNone(evidence['spans'][0]['input_tokens'])
        self.assertNotIn('PRIVATE', str(evidence))

    def test_finish_requires_closed_nonempty_bounded_trace_and_runs_once(self):
        callback = SentinelLangChainCallback()
        run_id = uuid4()
        callback.on_chain_start({}, {}, run_id=run_id)
        with self.assertRaises(ValueError):
            callback.finish({})
        callback.on_chain_end({}, run_id=run_id)
        evidence = callback.finish({})
        self.assertEqual(len(evidence['spans']), 1)
        with self.assertRaises(ValueError):
            callback.finish({})
        empty = SentinelLangChainCallback()
        with self.assertRaises(ValidationError):
            empty.finish({})

    def test_duplicate_events_are_ignored_and_bad_usage_is_not_coerced(self):
        callback = SentinelLangChainCallback()
        run_id = uuid4()
        callback.on_llm_start({'name': 'Model'}, ['PRIVATE'], run_id=run_id)
        callback.on_llm_start({'name': 'Duplicate'}, ['PRIVATE'], run_id=run_id)
        response = SimpleNamespace(llm_output={'usage': {
            'input_tokens': True, 'output_tokens': 1}}, generations=[])
        callback.on_llm_end(response, run_id=run_id)
        callback.on_llm_end(response, run_id=run_id)
        evidence = callback.finish({})
        self.assertEqual(len(evidence['spans']), 1)
        self.assertEqual(evidence['spans'][0]['name'], 'model.model')
        self.assertIsNone(evidence['spans'][0]['input_tokens'])


if __name__ == '__main__':
    unittest.main()
