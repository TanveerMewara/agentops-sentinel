"""Run after starting lessons.booking_api. Uses Python's standard library."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4


# Local lesson traffic goes directly to localhost, not an environment proxy.
opener = build_opener(ProxyHandler({}))


def request_json(base_url: str, path: str, payload: dict | None = None, timeout: float = 5):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def run_scenario(base_url: str, protected: bool) -> None:
    # New intended actions get new IDs. Retries reuse the same payload below.
    label = uuid4().hex
    payload = {"customer": f"lesson-{label}", "slot": "2030-01-15 10:00"}
    if protected:
        payload["operation_id"] = label
    print("\nWITH operation ID" if protected else "WITHOUT operation ID")

    try:
        request_json(base_url, "/bookings", {**payload, "response_delay_seconds": 2}, timeout=0.5)
    except TimeoutError:
        print("Client stopped waiting for the delayed HTTP reply.")
    else:
        raise AssertionError("Expected a client timeout from the injected delay.")

    result = request_json(base_url, "/bookings", payload)
    actual = [b for b in request_json(base_url, "/bookings") if b["customer"] == payload["customer"]]
    expected = 1 if protected else 2
    print(f"Retry returned {result['booking_id']}; actual appointments: {len(actual)}")
    assert len(actual) == expected, f"Expected {expected}, found {len(actual)}"

    if protected:
        try:
            request_json(base_url, "/bookings", {**payload, "slot": "2030-01-15 11:00"})
        except HTTPError as error:
            assert error.code == 409, f"Expected conflict, received {error.code}"
            print("Changed details with the same ID: HTTP 409 Conflict.")
        else:
            raise AssertionError("Changed details should be rejected.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        request_json(args.base_url, "/health")
    except URLError as error:
        raise SystemExit("Cannot reach the API. Start the server in another terminal first.") from error
    run_scenario(args.base_url, protected=False)
    run_scenario(args.base_url, protected=True)
    try:
        request_json(args.base_url, "/bookings", {"customer": " "})
    except HTTPError as error:
        assert error.code == 422, f"Expected invalid input rejection, received {error.code}"
        print("\nInvalid input: HTTP 422. All lesson checks passed.")
    else:
        raise AssertionError("Invalid input should be rejected.")


if __name__ == "__main__":
    main()
