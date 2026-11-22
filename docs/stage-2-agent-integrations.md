# Stage 2: external-agent integrations

Stage 2 proves that AgentOps Sentinel accepts agent evidence through public client and
framework interfaces without adding framework behavior to Sentinel's core runtime.
Three runnable agent paths are included:

1. `examples/support_triage_agent.py`: a plain Python agent using `TraceRecorder`.
2. `examples/langgraph_external_agent.py`: a real compiled LangGraph using
   `SentinelLangChainCallback`.
3. `examples/openai_agents_sdk_agent.py`: an OpenAI Agents SDK `Runner` using
   `SentinelOpenAIAgentsProcessor`.

The OpenAI Agents SDK processor uses the SDK's custom tracing-processor interface.
It retains structural span type, safe operation name, hierarchy, timing, status and
available token totals. It discards prompts, responses, model names, tool arguments,
tool results, trace metadata and exception text. Evidence remains caller-reported;
it is not independent proof that every operation was captured.

## Run the examples

Start the native API and configure the existing local developer and worker keys.
Then run any example with a stable key:

```powershell
.\.venv\Scripts\python.exe examples\support_triage_agent.py --key stage2-support-1 --topic billing --severity high
.\.venv\Scripts\python.exe examples\langgraph_external_agent.py --key stage2-graph-1 --mode success
.\.venv\Scripts\python.exe examples\langgraph_external_agent.py --key stage2-graph-failed --mode failed
.\.venv\Scripts\python.exe examples\langgraph_external_agent.py --key stage2-graph-review --mode interrupted
.\.venv\Scripts\python.exe examples\openai_agents_sdk_agent.py --key stage2-openai-1 --mode offline
```

The OpenAI example's offline mode still executes an actual SDK `Agent` and `Runner`.
It uses the SDK's deterministic `ScriptedModel`, so it needs no paid credential and
does not make a network call. Failure and interruption modes exercise failed model
and triggered-guardrail evidence.

For a live OpenAI model trial, explicitly provide both the credential and model:

```powershell
$env:OPENAI_API_KEY = "your-key"
.\.venv\Scripts\python.exe examples\openai_agents_sdk_agent.py `
  --key stage2-openai-live-1 --mode live --model "your-supported-model" `
  --task "A customer cannot update their billing method"
```

The live command is implemented but has not been executed in this repository because
no `OPENAI_API_KEY` is configured. Sentinel never receives that key or stores the
task. The example accepts only four bounded classification outputs before submitting
the result. The SDK model call is external and may incur provider charges.

All examples require `SENTINEL_DEVELOPER_API_KEY` and `SENTINEL_WORKER_API_KEY`.
`SENTINEL_API_URL` defaults to `http://127.0.0.1:8000`. Replaying the same key reads
the immutable saved trace instead of executing the agent again.

Pass `--dataset-id` to the LangGraph or OpenAI example to evaluate a successful run.
The supplied dataset must contain the case key `agent-run`. Dataset creation and
rule semantics are documented in [output evaluations](output-evaluations.md) and
[trajectory evaluations](trajectory-evaluations.md).

## Verification and completion boundary

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_framework_examples tests.test_openai_agents_trace -v
.\.venv\Scripts\python.exe tests\acceptance_access_client.py
.\.venv\Scripts\python.exe tests\acceptance_external_traces.py
```

The PostgreSQL acceptance gate records five domains: plain support, code-analysis,
LangGraph, OpenAI Agents SDK and standard OTLP. It finalizes immutable traces and
runs one passing `agent_rules_v4` experiment across all five, while also checking
replay conflicts, role and tenant isolation, private-data exclusion, request limits,
and unchanged governed tool/model ledgers.

This completes the local Stage 2 integration milestone. A live OpenAI provider call,
an outside-developer installation and independent-user evidence remain external
validation work and must not be inferred from the deterministic local SDK run.
