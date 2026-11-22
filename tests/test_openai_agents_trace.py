import unittest

from agents import (
    agent_span, function_span, generation_span, guardrail_span,
    set_trace_processors, trace,
)

from sentinel.integrations.openai_agents_trace import SentinelOpenAIAgentsProcessor


class OpenAIAgentsTraceTests(unittest.TestCase):
    def tearDown(self):
        set_trace_processors([])

    def test_real_sdk_trace_is_privacy_filtered(self):
        processor = SentinelOpenAIAgentsProcessor()
        set_trace_processors([processor])
        with trace("PRIVATE customer workflow") as sdk_trace:
            with agent_span("support_agent"):
                with generation_span(
                    input=[{"role": "user", "content": "PRIVATE PROMPT"}],
                    output=[{"role": "assistant", "content": "PRIVATE RESPONSE"}],
                    model="private-model-name",
                    usage={"input_tokens": 7, "output_tokens": 3},
                ):
                    pass
                with function_span("lookup_account", input="PRIVATE ARGUMENT",
                                   output="PRIVATE TOOL RESULT"):
                    pass
        body = processor.finish({"queue": "billing"}, trace_id=sdk_trace.trace_id,
                                idempotency_key="openai-agents-test")
        self.assertEqual(body["source"], "openai_agents")
        self.assertEqual(body["output"], {"queue": "billing"})
        self.assertEqual({span["kind"] for span in body["spans"]},
                         {"agent", "model", "tool"})
        model = next(span for span in body["spans"] if span["kind"] == "model")
        self.assertEqual((model["input_tokens"], model["output_tokens"]), (7, 3))
        serialized = str(body)
        for private in ("PRIVATE PROMPT", "PRIVATE RESPONSE", "PRIVATE ARGUMENT",
                        "PRIVATE TOOL RESULT", "private-model-name"):
            self.assertNotIn(private, serialized)

    def test_errors_and_triggered_guardrails_keep_no_error_text(self):
        processor = SentinelOpenAIAgentsProcessor()
        set_trace_processors([processor])
        with trace("guarded") as sdk_trace:
            with agent_span("review_agent"):
                with guardrail_span("policy_check", triggered=True):
                    pass
                failed = function_span("unsafe_action", input="PRIVATE")
                failed.start()
                failed.set_error({"message": "PRIVATE ERROR", "data": {"secret": "PRIVATE"}})
                failed.finish()
        body = processor.finish({}, trace_id=sdk_trace.trace_id,
                                reported_status="needs_review",
                                idempotency_key="openai-agents-guardrail")
        statuses = {span["status"] for span in body["spans"]}
        self.assertIn("needs_review", statuses)
        self.assertIn("failed", statuses)
        self.assertNotIn("PRIVATE", str(body))

    def test_multiple_traces_require_selection_and_cannot_refinalize(self):
        processor = SentinelOpenAIAgentsProcessor()
        set_trace_processors([processor])
        with trace("first") as first:
            with agent_span("first_agent"):
                pass
        with trace("second") as second:
            with agent_span("second_agent"):
                pass
        with self.assertRaisesRegex(ValueError, "Select exactly one"):
            processor.finish({})
        processor.finish({}, trace_id=first.trace_id,
                         idempotency_key="openai-agents-first")
        with self.assertRaisesRegex(ValueError, "already finalized"):
            processor.finish({}, trace_id=first.trace_id,
                             idempotency_key="openai-agents-first")
        self.assertIn(second.trace_id, processor.trace_ids())

    def test_open_span_and_span_limit_fail_closed(self):
        processor = SentinelOpenAIAgentsProcessor()
        set_trace_processors([processor])
        sdk_trace = trace("open")
        sdk_trace.start()
        span = agent_span("open_agent")
        span.start()
        with self.assertRaisesRegex(ValueError, "trace and spans have closed"):
            processor.finish({}, trace_id=sdk_trace.trace_id,
                             idempotency_key="openai-agents-open")
        span.finish()
        sdk_trace.finish()

        processor = SentinelOpenAIAgentsProcessor()
        set_trace_processors([processor])
        with trace("overflow") as overflow:
            for index in range(101):
                with function_span(f"tool_{index}"):
                    pass
        with self.assertRaisesRegex(ValueError, "100-span"):
            processor.finish({}, trace_id=overflow.trace_id,
                             idempotency_key="openai-agents-overflow")


if __name__ == "__main__":
    unittest.main()
