# Lesson 1: A timeout does not prove an action failed

## What we are learning

Imagine submitting a viewing request. The appointment service saves it, but its
reply never reaches you. Sending the request again could create two appointments.
The service knows what happened; the caller does not. That difference in knowledge
is the problem this lesson demonstrates.

The eventual flow is:

```text
Person -> EstateFlow proposes an action -> Sentinel checks and executes it
                                       -> External booking or CRM service
```

EstateFlow will interpret enquiries and propose work. Sentinel will control how
actions are approved, attempted, recorded, and recovered. The external service
owns the actual booking or customer record. Sentinel cannot simply assume that
its own records perfectly describe that external service.

## Technology introduced: Python

Python is the programming language for this experiment. We use its built-in
features, so no packages or API keys are needed.

- A **class** groups related state and behaviour. `BookingService` holds the
  appointments and the function that creates them.
- A **dataclass** provides a short way to describe a record. `Booking` contains
  an ID, customer, and appointment time. `frozen=True` prevents normal reassignment
  of its fields after creation.
- A **list** stores the appointments. A **dictionary** maps an operation ID to
  the result already created for that operation.
- **Type hints**, such as `str` and `list[Booking]`, describe intended values.
  They help readers and checking tools; they do not automatically validate inputs.
- An **exception** signals a problem. We deliberately raise `TimeoutError` after
  creating a booking. `try` and `except` let the caller react to that error.
- An **assertion** checks an expected result and fails loudly if it is false.
  These assertions verify the lesson; they are not production input validation.

## Read the program in this order

Open `lessons/01_lost_response.py`.

1. `Booking` describes a single appointment.
2. `BookingService.__init__` starts with empty lists and records. `self` refers
   to that particular service object.
3. `create_booking` first checks whether the operation ID already has a result.
   If so, it verifies that the details match and returns the original booking.
4. Otherwise, it creates and saves the booking. Only after saving it can our
   simulated lost response raise an exception. This ordering is the key detail.
5. `run_scenario` plays the caller. It tries once, sees a timeout, and retries.
   Each scenario gets a fresh service so the two results are independent.
6. `main` runs both scenarios and checks the actual appointments, including a
   check that changed details cannot reuse the same operation ID.
7. The `if __name__ == "__main__"` line runs `main` when you execute this file
   directly, rather than when another Python file imports it.

In a function signature, `*` means the following arguments must be named when
calling it. `str | None` means a value can be text or absent. An `f"..."` string
inserts values inside braces into the printed text.

## The idea behind the fix

An **operation ID** identifies one intended action. Think of it as a claim ticket:
showing the same ticket twice should retrieve the same result, not create another
appointment. A retry keeps its ticket; a genuinely new action gets a new ticket.

This behaviour is called **idempotency**: repeating the operation has the same
intended effect as performing it once. It is not achieved just by including a
random ID. Here, the booking service explicitly stores and checks that ID.

The operation ID and booking ID have different jobs. The caller supplies an
operation ID before execution; the service creates a booking ID for the result.
Do not use customer name and appointment time alone as the operation identity:
identical-looking requests are not necessarily the same intended action.

## Run and observe

From the project folder in PowerShell:

```powershell
python lessons/01_lost_response.py
```

`python` starts the interpreter, and the path tells it which file to execute.
Watch the service print "created" before the caller prints "received a timeout".
The final counts should be two without protection and one with protection.

## What this does not solve yet

- The service is a Python object, not a separate process or real HTTP API.
- Memory disappears when the program exits. This does not demonstrate recovery
  after a restart.
- Calls run sequentially. The check followed by creation is not a safe concurrent
  database implementation.
- The operation ID is fixed for teaching. A real workflow must create and persist
  the identity of each action and protect it with the appropriate tenant scope.
- Our pretend service supports deduplication. An external service might not.
- No prompt or LLM is needed to reproduce this failure; adding an agent later
  will not remove the underlying execution problem.

## Understanding checkpoint

Explain these in your own words before our next milestone:

1. Why can the caller receive a timeout even though the appointment exists?
2. What would happen if the retry generated a new operation ID?
3. Where is the duplicate prevented: the caller or the booking service?
4. Why does this experiment not prove that bookings are safe after a restart?

Optional experiment: change the retry's operation ID to a different value and
rerun. Predict the appointment count first. The protected scenario's assertion
should fail because the new ID represents another operation. Restore it afterward.

## Next milestone

Separate the caller and booking service using an HTTP API. Introduce HTTP,
requests, responses, JSON, and FastAPI through this same example. The business
problem stays familiar while we add a real communication boundary.
