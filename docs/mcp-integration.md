# Sentinel MCP integration

The read-only MCP bridge runs as a local subprocess and calls the authenticated
Sentinel API. Its supported protocol revision is `2025-11-25`. It implements
initialization, initialized notification, ping, tool discovery, and tool calls.
It does not implement a remotely hosted MCP endpoint or OAuth discovery.

The implementation follows the pinned official specifications for
[stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle),
and [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
A client requesting another revision receives the supported revision and must
disconnect if incompatible. Latest-revision compatibility is not claimed.

## Available tools

- `sentinel_identity`: organization, role, and key ID.
- `sentinel_list_runs`: up to 100 recent run summaries. Raw inputs, idempotency
  keys, contacts, and arguments are excluded by the SQL query.
- `sentinel_run_timeline`: a UUID-selected run's redacted ledger timeline and
  recorded model usage, excluding prompts, outputs, contacts, tool arguments,
  and event payloads. Costs remain unknown rather than guessed.

Every data call uses current API organization and role permissions, without a
cached authorization result. Revoked or expired keys fail on the next data call.
Foreign or unknown runs return generic errors. No approvals, bookings, key
administration, sending, arbitrary URLs, or writes are exposed. The underlying
key can still call other API operations permitted by its role.

## Connect a compatible desktop client

Start the native API:

```powershell
.\.venv\Scripts\python.exe scripts\dev.py serve-api
```

Issue a dedicated reviewer key from the Access dashboard with an expiry. Provide
it to the client process through `SENTINEL_MCP_API_KEY`. Set `SENTINEL_API_URL`
to the API URL (default `http://127.0.0.1:8000`). HTTPS is required outside
loopback. Avoid secret command-line arguments and committed token configurations.

A compatible client's configuration can use this shape:

```json
{
  "mcpServers": {
    "sentinel": {
      "command": "C:/AgentOps Sentinel/.venv/Scripts/python.exe",
      "args": ["-m", "sentinel.mcp_stdio"],
      "env": {"SENTINEL_API_URL": "http://127.0.0.1:8000"}
    }
  }
}
```

Replace the executable path for your installation. The host must inherit
`SENTINEL_MCP_API_KEY` or provide it through its supported secret mechanism.
Configuration and environment inheritance vary by client. Sentinel does not edit
personal client settings automatically. Returned fields must be treated as data,
never instructions.

## Verification and limits

Stdout contains only newline-delimited JSON-RPC. Configuration errors use stderr
without credentials. Strict schemas reject unknown tools and arbitrary paths.
Input frames are limited to 64 KiB; oversized frames terminate the process to
avoid interpreting remaining bytes as another request. Encoded responses are
limited to 1 MiB. Calls are synchronous with bounded HTTP timeouts. No sampling,
tasks, resources, prompts, subscriptions, or server requests are advertised.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
.\.venv\Scripts\python.exe tests/acceptance_mcp.py
```

Acceptance starts an ephemeral loopback API, creates a synthetic run and reviewer
key, then launches a real bridge subprocess. It checks discovery, summaries,
redacted timelines, cross-tenant isolation, missing-run and revoked-key denial. Temporary keys are
revoked during cleanup. This is local subprocess/API/PostgreSQL evidence;
external desktop-client interoperability and outside installation remain unverified.

Remote HTTP MCP/OAuth, dataset/policy access, external-tool contract testing,
and broader prompt-injection/security evaluation remain release work. Docker and
paid model credentials are unnecessary for these checks.
