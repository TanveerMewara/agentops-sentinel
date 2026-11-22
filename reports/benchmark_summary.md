# AgentOps Sentinel benchmark summary

Run ID: `6f33a0bee4ff4e778a37a37606b9d94e`  
Completed: `2026-09-22T21:26:53.565510+00:00`  
Dataset SHA-256: `ced989ca055e81ef80115603ae4012928ff82426450e53944345f62fc596fe9d`  
Source-tree SHA-256: `0368d9916a86c9f31c9feeb4f9c7e20ca3850dcdebfb6cb7c2a8a47cfc937125`

| Metric | Result |
|---|---:|
| Agent executions | 960 |
| Traces processed | 720 |
| Tool calls monitored | 720 |
| Failure scenarios | 20 |
| Failure-detection accuracy | 100.00% |
| Macro precision | 100.00% |
| Macro recall | 100.00% |
| Macro F1 | 100.00% |
| Observed P50 latency | 2.718 ms |
| Observed P95 latency | 6.937 ms |
| Observed P99 latency | 35.453 ms |
| Mean monitoring overhead | 1.708 ms / 72.68% |
| Automated unit tests | 225 |
| Test pass rate | 100.00% |
| Backend code coverage | 31.73% |
| Observed synthetic token units | 39360 |
| Average synthetic token units/execution | 164.00 |
| Observed estimated cost/execution | $0.00009000 |
| Measured reference-workflow cost reduction | 87.78% |
| Execution success rate under injection | 41.67% |
| Recovery rate under injection | 83.33% |

## Evidence boundaries

- Failure cases and provider token usage are controlled synthetic fixtures.
- Baseline and observed arms execute identical agent logic; their paired delta measures monitoring overhead.
- The optimized arm is a measured reference-workflow change using exact-key caching and reduced context. Sentinel does not automatically rewrite agents.
- Estimated cost uses the report's declared synthetic rate card. It is not a provider invoice.
- Results describe this machine and run. They do not establish production-user scale or real-world failure prevalence.

## Optimization evidence

Observed used 39360 synthetic token units and estimated $0.02160000. 
The optimized reference workflow used 3360 units and estimated $0.00264000. 
The measured estimated-cost change was 87.78% reduction.
