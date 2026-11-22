# Lesson 4: Describe what we know before deciding what to do

## Why we can learn this while Docker is blocked

Lesson 3's PostgreSQL integration still needs verification. This separate Python
experiment has no database dependency. It introduces decision rules for Sentinel's
future execution layer without claiming that persistent recovery already works.
The complete product scope remains in ../product-scope.md.

## The central distinction

An appointment can exist in the booking service while Sentinel does not yet know
it exists. These are two different facts:

- External reality: what the booking service actually did.
- Sentinel's knowledge: what evidence Sentinel has received.

UNKNOWN describes Sentinel's knowledge, not proof that the appointment is missing.
The rules in this lesson prevent us from quietly converting uncertainty into failure.

## Our six states

- READY: the lesson operation has not started. This does not mean a real user has
  authorized it; permissions and approval are not implemented here.
- EXECUTING: the request has been started.
- UNKNOWN: the reply timed out; the action might have completed.
- SUCCEEDED: a simulated confirmation supplied the booking ID.
- FAILED: a simulated authoritative rejection says no effect occurred.
- NEEDS_REVIEW: automatic verification could not establish the outcome.

A state is a label describing the operation now. An event describes what happened.
A transition is an allowed change from one state to another. A state machine is
simply a set of these allowed changes. It is ordinary code, not an AI model.

For example:

```text
READY -> EXECUTING -> UNKNOWN -> SUCCEEDED
                            -> NEEDS_REVIEW
```

There is intentionally no UNKNOWN -> EXECUTING rule in this first model. A timeout
alone is not enough reason to try the action again. Later adapters may allow safe
replay when a service provides suitable guarantees, but that requires explicit rules.

## Run the experiment

From the project folder:

```powershell
.\.venv\Scripts\python.exe lessons/04_operation_states.py
```

This uses only Python's standard library. Docker and API keys are unnecessary.

The script starts one operation, records a timeout, and demonstrates that a blind
retry is rejected. It then shows two alternate, simulated possibilities:

1. A trustworthy lookup confirms a booking: record SUCCEEDED and its booking ID.
2. Verification cannot establish the outcome: record NEEDS_REVIEW.

These branches illustrate different possible outcomes; they do not both happen to
one real appointment. The script does not contact a service.

## Read the code in order

Open lessons/04_operation_states.py.

1. State and Event inherit from Enum. An enum defines a named set of values, so we
   can use State.UNKNOWN instead of repeatedly typing error-prone strings.
2. TRANSITIONS is a dictionary. Its key is a pair: (current state, event). Its value
   is the allowed next state. Absence of a pair means that transition is forbidden.
3. Operation is a dataclass holding the ID, state, optional result, and history.
   frozen=True prevents ordinary reassignment of fields. History is a tuple, which
   cannot be appended to in place like a list.
4. advance looks up an allowed transition and checks whether result data is valid.
   A success needs a nonempty booking ID; other events cannot attach a booking ID.
5. replace creates a new Operation with updated fields. The old record stays intact.
6. The new history adds a readable explanation of the transition.
7. main demonstrates the rules with fictional input.

This is a pure decision function: it does not write a database or call a network.
Given the same input record and event, it produces the same result or rejection.
Separating decision rules from storage makes them easy to inspect and test.

## Evidence is a future integration responsibility

A nonempty booking ID is not proof by itself. This lesson trusts the supplied event.
A real adapter must verify the service response, associate it with the exact
operation, and prevent arbitrary callers or an LLM from inventing confirmation.

Similarly, HTTP 500 alone is NOT REJECTED_WITHOUT_EFFECT: a service can fail after
performing the action. Even a 'not found' lookup can be misleading if the original
request is still running or the lookup is stale. This model has no automatic retry
path from UNKNOWN for those reasons.

NEEDS_REVIEW has no resolution path yet. We will design the human workflow and
its authorization separately. History here is not persistent, tamper-proof, or a
production audit log. Immutable Python objects are not a concurrency guarantee.

## Verify the rules

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_operation_states.py -v
```

unittest is Python's built-in test framework. Each test checks a behaviour we care
about: timeout classification, forbidden retries, confirmed results, input checks,
human-review routing, and terminal-state protection. The tests use simulated events;
they do not prove recovery from a real server crash.

## Try one change mentally first

Suppose UNKNOWN could immediately transition to EXECUTING on START. Which failure
from Lesson 1 would become possible again? The point of the state machine is to
make that unsafe choice visible and prevent it unless we design a justified policy.

## Where this fits next

Once PostgreSQL is working, we will verify Lesson 3. Then we can persist operations
and attempts, connect these decision rules to actual tool responses, and handle
concurrent workers safely. Approval, tracing, evaluations, and the broader Sentinel
features remain later milestones; this file is a teaching model of one component.
