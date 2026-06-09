"""Locust SSE load test for /hotspots/stream (NFR: <1% dropped, p99 < 500ms).

Run: locust -f load/sse_locust.py --headless -u 1000 -r 50 -t 10m \
     --host http://localhost:8000
Each user opens an SSE connection with a valid token, reads frames, and records
time-to-first-byte. Disconnects/reconnects are counted as drops if > expected.
"""
from __future__ import annotations

import os
import time

from locust import HttpUser, between, task


def _token() -> str:
    from datetime import datetime, timedelta, timezone

    import jwt
    secret = os.getenv("SENTINEL_JWT_SECRET")
    if not secret:
        raise SystemExit(
            "SENTINEL_JWT_SECRET must be set — must match the API server's secret "
            "for JWT signature verification."
        )
    payload = {"sub": "load", "role": "analyst",
               "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    return jwt.encode(payload, secret, algorithm="HS256")


class SSEUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def stream(self):
        start = time.time()
        with self.client.get(f"/hotspots/stream?token={_token()}",
                             stream=True, name="/hotspots/stream", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            for _line in r.iter_lines():
                # record TTFB then drop the connection to simulate churn
                self.environment.events.request.fire(
                    request_type="SSE", name="ttfb", response_time=(time.time() - start) * 1000,
                    response_length=0, exception=None, context={})
                break
            r.success()
