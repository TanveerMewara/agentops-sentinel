# API response security and network checks

Sentinel applies `X-Content-Type-Options: nosniff`, `Referrer-Policy:
no-referrer`, and `X-Frame-Options: DENY` to responses passing through its
response middleware. `/v1/` responses also use `Cache-Control: no-store`,
including ordinary authorization, validation, and missing-route errors.
These headers do not encrypt traffic; production connections require HTTPS.

## Validation errors

Request-validation errors report only the transport location (`body`, `query`,
`path`, `header`, or `cookie`), a fixed message, and a fixed error type. They omit
submitted values, arbitrary field names, validator messages, and context, which
can contain private content. Clients should validate forms locally for detailed
field guidance. The server still rejects invalid requests.

This is a boundary for request validation, not a general-purpose redactor.
Successful responses, deliberate business errors, run inputs, third-party logging,
proxy logs, and unexpected server failures need their own review. Keys must stay
out of URLs and logs. The middleware does not promise to decorate unhandled 500
responses generated outside it.

## Repeatable verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

`test_http_security.py` submits sensitive-looking synthetic values, extra field
names, malformed JSON, and a validator that echoes its input. Responses must omit
those values and messages. It also checks response policies on errors.

`test_client_network.py` uses real loopback sockets. GET and POST redirects for
301, 302, 303, 307, and 308 must cause zero destination requests and exactly one
initial attempt. A temporary self-signed localhost certificate must fail with
default trust settings before an HTTP request arrives. Explicitly trusting only
that test certificate permits a verified HTTPS JSON exchange. Verification stays
enabled; certificate material is temporary and synthetic.

These are local protocol checks, not hosted deployment evidence, an outside
developer pilot, or a full security assessment. Prompt injection, data access
review, rate limits, production identity, and proxy/monitoring redaction remain
release work. No Docker or external account is required.
