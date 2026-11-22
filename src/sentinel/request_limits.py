"""Atomic per-key fixed windows shared by API replicas using PostgreSQL."""
import math
from datetime import timedelta


def consume_request(connection, key_id, limit, window_seconds):
    connection.execute("""INSERT INTO sentinel_request_limits(api_key_id,window_started_at,request_count)
                          VALUES (%s,clock_timestamp(),0) ON CONFLICT DO NOTHING""", (key_id,))
    row = connection.execute("SELECT * FROM sentinel_request_limits WHERE api_key_id=%s FOR UPDATE", (key_id,)).fetchone()
    # Read database time after acquiring the row lock. A competing request may
    # have held it across the window boundary.
    now = connection.execute("SELECT clock_timestamp() AS current_time").fetchone()["current_time"]
    reset = row["window_started_at"] + timedelta(seconds=window_seconds) <= now
    started = now if reset else row["window_started_at"]
    count = 1 if reset else min(row["request_count"] + 1, limit + 1)
    allowed = count <= limit
    connection.execute("""UPDATE sentinel_request_limits SET window_started_at=%s, request_count=%s,
                          blocked_count=blocked_count+%s,
                          last_blocked_at=CASE WHEN %s THEN %s ELSE last_blocked_at END
                          WHERE api_key_id=%s""", (started, count, int(not allowed), not allowed, now, key_id))
    return allowed, max(1, math.ceil((started + timedelta(seconds=window_seconds) - now).total_seconds()))
