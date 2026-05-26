"""
Database connection utilities for Sentinel.

This module provides both direct connections (legacy) and pooled connections (recommended).
For new code, prefer get_pooled_connection().
"""

from __future__ import annotations

import os
import warnings

import psycopg2

from pipeline.pool import SentinelConnectionPool, get_pooled_connection as _pooled_conn


def get_connection():
    """
    Get a direct database connection.

    DEPRECATED: This function creates a new connection each time, which is
    inefficient under load. Use get_pooled_connection() instead.

    This function will be removed in a future version.
    """
    warnings.warn(
        "get_connection() is deprecated. Use get_pooled_connection() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "5433")),
        dbname=os.getenv("PGDATABASE", "sentinel"),
        user=os.getenv("PGUSER", "sentinel_user"),
        password=os.getenv("PGPASSWORD", "sentinel_pass"),
        connect_timeout=10,
    )


def get_pooled_connection():
    """
    Get a pooled database connection (recommended).

    Returns:
        tuple: (connection, pool_instance)

    Usage:
        conn, pool = get_pooled_connection()
        try:
            # use connection
            pass
        finally:
            pool.return_connection(conn)

    See: pipeline.pool.SentinelConnectionPool
    """
    return _pooled_conn()
