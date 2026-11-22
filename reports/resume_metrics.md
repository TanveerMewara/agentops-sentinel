# Resume metrics supported by benchmark evidence

- Controlled evaluation predictions: 240
- Failure categories including no-failure control: 11
- Macro failure-detection F1: 100.00%
- Total benchmark agent executions: 960
- Concurrent load executions: 240
- Total monitored traces: 720
- Concurrent load throughput: 248.11 executions/second
- Mean paired monitoring overhead: 1.708 ms (72.68%)
- Recovery rate in controlled failure injection: 83.33%
- Automated unit tests: 225
- Backend statement coverage: 31.73%

## Resume bullets

- Built a versioned AI-agent failure-diagnostics benchmark spanning 10 failure categories and 240 controlled predictions, measuring 100.00% macro F1 with a reproducible confusion matrix.
- Benchmarked Sentinel instrumentation across 960 total executions and 720 monitored traces, including a 240-execution concurrent load at 248.11 executions/second with 5.161 ms P95 paired overhead.
- Validated reliability across 20 controlled failure scenarios with 83.33% recovery and 55.56% retry success, backed by 225 passing automated unit tests.

All figures above come from `benchmark_results.json`. Synthetic evidence must remain labeled as controlled benchmark evidence.
