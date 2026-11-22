# LangChain and LangGraph trace adapter

`SentinelLangChainCallback` converts LangChain Core callbacks, including callbacks
emitted by LangGraph, into Sentinel's bounded external-trace format. It records
operation names, parent relationships, timing, completion/failure status and model
token totals when the provider exposes them.

The adapter intentionally ignores prompts, chat messages, chain inputs and outputs,
tool arguments and results, retrieved documents, exception messages, tags and
metadata. You explicitly choose the sanitized final JSON output sent to Sentinel.

```python
from sentinel.integrations.langchain_trace import SentinelLangChainCallback

callback = SentinelLangChainCallback(source="langgraph")
result = graph.invoke(
    {"request": request},
    config={"callbacks": [callback]},
)

evidence = callback.finish(
    {"answer": result["answer"]},
    reported_status="succeeded",
    idempotency_key="support-run-0001-trace",
)
client.submit_external_trace(run_id, evidence)
```

Keep the evidence payload returned by `finish` until submission is confirmed. If a
write times out, replay that exact payload and idempotency key. Create one callback
per agent run. Call `finish` only after framework execution and all callbacks have
closed. A failed invocation should be caught by the integration so it can finalize
a sanitized error output with `reported_status="failed"`; exception text is never
captured automatically.

## Stable operation names

The adapter normalizes framework component names into lowercase bounded identifiers:

- chains and graph nodes: `agent.<component>`
- language/chat models: `model.<component>`
- tools: `tool.<component>`
- retrievers: `retrieval.<component>`

For example, `Send Reply` becomes `tool.send-reply`. These names can be used in
trajectory datasets. Framework refactors can change emitted component names, so a
renamed node or tool should normally accompany a new immutable dataset version.

Token usage is recorded only when a callback response supplies a valid nonnegative
input/output pair through standard LangChain usage fields. Otherwise both values
stay unknown; Sentinel never estimates them. The callback accepts at most 100 spans,
and final evidence still passes all normalized-size, tree, timing and JSON checks.

## Evidence boundary

This is supported callback capture for the installed LangChain Core/LangGraph
versions. The resulting evidence remains caller-reported because the callback runs
inside the integrated application process. It does not prove the application kept
the callback installed, captured every operation, or had Sentinel approval for an
external side effect.

`tests/test_langchain_trace.py` verifies a real compiled LangGraph invocation plus
payload exclusion, usage extraction, failures, duplicate events and finalization.
`tests/acceptance_external_traces.py` submits evidence from a compiled graph through
the API into real PostgreSQL and verifies replay, privacy, tenant boundaries and
unchanged governed ledgers. Real hosted-model and outside-application trials remain
required before claiming broader framework compatibility.
