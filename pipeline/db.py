from __future__ import annotations

import os

import psycopg2


def get_connection():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "5433")),
        dbname=os.getenv("PGDATABASE", "sentinel"),
        user=os.getenv("PGUSER", "sentinel_user"),
        password=os.getenv("PGPASSWORD", "sentinel_pass"),
    )
