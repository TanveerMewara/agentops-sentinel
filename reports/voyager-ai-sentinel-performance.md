# Voyager AI + AgentOps Sentinel performance report

Measured: 14 October 2026  
Sentinel benchmark run: `05e0b03e3f824051990bc2e538592c5a`  
Voyager endpoint: deployed `POST /api/plan`  
Workload: synthetic two-day solo Paris trip from London  
Samples: 3 direct Voyager calls and 3 Sentinel-monitored Voyager calls

## Connection result

The live integration succeeded. Sentinel registered Voyager AI as an external agent,
created immutable version `1.0.0`, created runs, accepted structural traces and
completed the monitored runs. The initial live verification produced Sentinel run
`b22bfc94-83b3-4883-83f8-144da48acc01` and trace
`0379b1cc-883d-4931-830a-df8474e17103`.

The verification call completed in 6,069 ms. Voyager reported first text at 0.552 s
and server generation completion at 2.955 s. Sentinel run creation, trace submission
and completion took 83 ms, 109 ms and 55 ms respectively in that call.

## Benchmark results

| Measurement | Mean | P50 | P95 |
|---|---:|---:|---:|
| Direct Voyager completion | 3,465 ms | 3,169 ms | 4,272 ms |
| Voyager completion inside monitored runs | 4,246 ms | 3,594 ms | 5,948 ms |
| Sentinel run creation | 64 ms | 55 ms | 89 ms |
| Sentinel trace submission | 150 ms | 131 ms | 281 ms |
| Sentinel run completion | 79 ms | 41 ms | 170 ms |
| Complete monitored pipeline | 4,542 ms | 3,718 ms | 6,448 ms |

All 3 monitored runs completed. Mean Sentinel API work was approximately **293 ms**
per run: 64 ms creation + 150 ms trace ingestion + 79 ms completion. The complete
monitored pipeline averaged about 296 ms more than its contained Voyager call,
roughly 7.0% of mean monitored Voyager latency.

The instrumented Voyager calls averaged 781 ms slower than the direct calls in this
six-call run. That difference must not be attributed entirely to Sentinel: direct
and monitored calls are different Gemini/Vercel/network executions, all three
monitored responses had different normalized fingerprints, and the trace recorder
performs no Sentinel network call while Voyager is generating. Sentinel ingestion
can remain outside Voyager's user-facing critical path when submitted asynchronously.

## Privacy and trust boundary

Sentinel stored the request fingerprint, structural operation names, timings,
reported status, response size and response fingerprint. It did not store the
travel request, generated plan, Gemini key, weather key or any Voyager credential.
A response fingerprint establishes normalized JSON identity only; it does not prove
that a travel plan is factually correct, current, safe or bookable.

## Limits

This is a minimum useful integration check, not a production SLA. Three samples are
too few for stable tail-latency claims. Results describe this laptop, network, Vercel
deployment, Gemini provider conditions and one synthetic request on 14 October 2026.
A serious release decision should repeat at least 30-100 representative cases across
destinations, trip lengths, load levels and provider conditions, and evaluate plan
quality separately from operational performance.

The machine-readable private report is `.local/voyager-benchmark/latest.json`.
