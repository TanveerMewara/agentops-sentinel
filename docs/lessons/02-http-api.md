# Lesson 2: Two programs talking through an API

## What changed?

Lesson 1 called a function in the same program. Now the client sends a request to
another running program: our pretend booking server. Both run on your computer.
This server represents an external booking service, not the finished Sentinel backend.

## New technologies in plain language

- Client: the program asking for work; here, a Python script.
- Server: a program listening for requests and sending replies.
- API: the agreement about requests a program accepts and the data it returns.
- HTTP: the communication protocol. GET reads information; POST submits work.
- Endpoint: an API address and operation, such as POST /bookings.
- JSON: text containing structured data, such as {"customer": "Asha"}.
- FastAPI: maps incoming HTTP requests to our Python functions.
- Pydantic: checks incoming fields against BookingRequest and its constraints.
- Uvicorn: runs the FastAPI application and listens for connections.
- Virtual environment: .venv keeps this project's installed packages separate.
- pip: installs Python packages. requirements.txt pins direct dependencies; it is
  not a complete lockfile of all dependencies.

## Start the lesson

Run commands from C:\AgentOps Sentinel. Skip creating .venv if it already exists.
These commands use its Python directly, so activation is unnecessary.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

In terminal A:

```powershell
.\.venv\Scripts\python.exe -m uvicorn lessons.booking_api:app --host 127.0.0.1 --port 8000
```

The -m option runs a Python module. lessons.booking_api:app selects the app object
in lessons/booking_api.py. 127.0.0.1 means this computer; 8000 is the listening port.
Use one worker and no auto-reload: this lesson stores everything in process memory.

Leave terminal A running. In terminal B:

```powershell
.\.venv\Scripts\python.exe lessons/02_http_client.py
```

Expected: two appointments without an operation ID, one with it, HTTP 409 for
changed details, and HTTP 422 for invalid input. Each scenario uses a unique label,
so rerunning is safe without resetting the teaching server. Ctrl+C stops the server.

## Explore in your browser

Open http://127.0.0.1:8000/docs while the server runs. Select an endpoint and choose
Try it out. GET /health checks the server; GET /bookings lists saved appointments;
POST /bookings creates an appointment. Try this POST request body:

```json
{
  "customer": "Asha",
  "slot": "2030-01-15 10:00",
  "operation_id": "my-first-viewing",
  "response_delay_seconds": 0
}
```

Send it twice, then list bookings: this operation creates one appointment. Change
the slot while keeping the operation ID to see a conflict. All appointments are
fictional. The docs UI may need internet to load its assets; the client does not.

## Follow the server code

1. BookingRequest describes input. Field adds constraints: required nonempty text,
   maximum lengths, and a delay from zero to five seconds. ConfigDict rejects extra
   fields and strips surrounding whitespace. We do not yet validate actual dates,
   time zones, availability, user identity, or permissions.
2. Booking describes the output record.
3. app = FastAPI(...) creates the application. The list and dictionary store its
   appointments and operation results in memory.
4. @app.get and @app.post register functions for HTTP routes. These lines are
   decorators. response_model declares the response shape.
5. create_booking checks the operation ID. It returns the prior result if details
   match and raises HTTPException with code 409 if the details have changed.
6. Otherwise, it saves a booking BEFORE delaying its response.

async def defines a function that can pause at await. await asyncio.sleep lets
other requests proceed during the delay. The client giving up does not undo the
appointment. There is no await between the ID check and memory update, but this
is not a durable or multi-process concurrency guarantee.

## Follow the client code

request_json uses Python's built-in urllib to send requests. json.dumps converts
a Python dictionary into JSON text, encode makes bytes for transmission, and
json.load reads the response back into Python values. Local traffic bypasses
proxy settings. No extra client library is needed.

run_scenario generates a unique label with uuid4. New intended actions get new
IDs; retries reuse their ID. The first request asks for a two-second response delay,
but the client waits only half a second. It then retries without asking for a delay.

This is a real HTTP client timeout caused by an intentionally slow response. We
are not literally deleting network packets or covering every network failure.
The client reads the service's actual records to verify the appointment count.
Our lab allows that access; real external services might not.

## Understand the outcomes

- 200: successful request, including returning an existing booking on retry.
- 409: the operation ID conflicts with different action details.
- 422: input does not satisfy the required data shape or constraints.
- Timeout: the client stopped waiting. It received no HTTP status code for that
  timeout, and cannot infer whether the booking succeeded from the timeout alone.

assert statements check our lesson's expected outcomes; they are not production
input validation. The client deliberately retries for demonstration and does not
yet implement Sentinel's recovery policy. Duplicate protection comes from the server.

## Limits and next step

This local, single-process example has no authentication, tenant isolation, durable
storage, or real calendar integration. Restarting loses all records; multiple
workers would have separate memory. The delay field is for controlled local testing
and must not be exposed on a production booking API.

Try stopping and restarting the server, then inspect bookings. They disappear
because memory belongs to the running process. The next lesson introduces durable
storage and the need to save operation records and bookings consistently.

Understanding check: explain the difference between the server completing an action
and the client receiving its response. Then point to where each happens in the code.

References: https://fastapi.tiangolo.com/tutorial/first-steps/
and https://fastapi.tiangolo.com/tutorial/body/
