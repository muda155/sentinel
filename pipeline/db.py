"""
Database connection utilities for Sentinel.

Provides pooled connections via the SentinelConnectionPool singleton.
"""

from __future__ import annotations

from pipeline.pool import get_pooled_connection as _pooled_conn


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
