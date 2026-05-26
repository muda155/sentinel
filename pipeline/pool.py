"""
Sentinel Connection Pool

Provides a singleton connection pool using psycopg2.ThreadedConnectionPool.
Configured via environment variables.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

import psycopg2
from psycopg2 import pool


class SentinelConnectionPool:
    """
    Thread-safe singleton connection pool for Sentinel database.

    Usage:
        pool = SentinelConnectionPool.get_instance()
        conn = pool.get_connection()
        try:
            # use connection
            pass
        finally:
            pool.return_connection(conn)
    """

    _instance: Optional["SentinelConnectionPool"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        minconn: int = 2,
        maxconn: int = 10,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._host = host or os.getenv("PGHOST", "127.0.0.1")
        self._port = port or int(os.getenv("PGPORT", "6432"))  # pgbouncer default
        self._database = database or os.getenv("PGDATABASE", "sentinel")
        self._user = user or os.getenv("PGUSER", "sentinel_user")
        self._password = password or os.getenv("PGPASSWORD", "sentinel_pass")

        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._initialized = False
        self._init_lock = threading.Lock()

        self._minconn = minconn
        self._maxconn = maxconn

    @classmethod
    def get_instance(
        cls,
        minconn: int = 2,
        maxconn: int = 10,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> "SentinelConnectionPool":
        """
        Get the singleton pool instance. Creates on first call.

        Args:
            minconn: Minimum connections to maintain
            maxconn: Maximum connections allowed
            host: Override PGHOST
            port: Override PGPORT
            database: Override PGDATABASE
            user: Override PGUSER
            password: Override PGPASSWORD

        Returns:
            SentinelConnectionPool singleton instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(
                        minconn=minconn,
                        maxconn=maxconn,
                        host=host,
                        port=port,
                        database=database,
                        user=user,
                        password=password,
                    )
        return cls._instance

    def _ensure_initialized(self) -> None:
        """Lazy initialization of the connection pool."""
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    try:
                        # Use statement_timeout only when connecting directly to PostgreSQL
                        # (not through pgbouncer which doesn't support session-level options)
                        conn_opts = {
                            "host": self._host,
                            "port": self._port,
                            "dbname": self._database,
                            "user": self._user,
                            "password": self._password,
                            "connect_timeout": 10,
                        }
                        if self._port != 6432:
                            conn_opts["options"] = "-c statement_timeout=30000"

                        self._pool = pool.ThreadedConnectionPool(
                            self._minconn,
                            self._maxconn,
                            **conn_opts,
                        )
                        self._initialized = True
                    except psycopg2.Error as e:
                        raise ConnectionError(f"Failed to initialize connection pool: {e}")

    def get_connection(self):
        """
        Get a connection from the pool.

        Returns:
            psycopg2 connection object

        Raises:
            ConnectionError: If pool initialization or connection acquisition fails
        """
        self._ensure_initialized()
        try:
            conn = self._pool.getconn()
            # Ensure connection is usable
            conn.autocommit = False
            return conn
        except psycopg2.pool.PoolError as e:
            raise ConnectionError(f"Failed to get connection from pool: {e}")

    def return_connection(self, conn) -> None:
        """
        Return a connection to the pool.

        Args:
            conn: Connection to return
        """
        if self._pool is not None:
            self._pool.putconn(conn)

    def health_check(self) -> dict:
        """
        Perform a health check on the pool.

        Returns:
            dict with status, pool_stats, and connection_test results
        """
        result = {
            "status": "unknown",
            "pool_stats": {},
            "connection_test": None,
        }

        try:
            self._ensure_initialized()
            if self._pool is None:
                result["status"] = "not_initialized"
                return result

            # Test getting and returning a connection
            test_conn = self._pool.getconn()
            try:
                with test_conn.cursor() as cur:
                    cur.execute("SELECT 1 AS healthy")
                    result["connection_test"] = cur.fetchone()[0] == 1
            finally:
                self._pool.putconn(test_conn)

            # Get pool statistics (approximate based on min/max)
            result["pool_stats"] = {
                "min_connections": self._minconn,
                "max_connections": self._maxconn,
                "initialized": self._initialized,
            }

            result["status"] = "healthy" if result["connection_test"] else "unhealthy"

        except Exception as e:
            result["status"] = "error"
            result["connection_test"] = str(e)

        return result

    def close_all(self) -> None:
        """Close all connections in the pool."""
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
            self._initialized = False

    def __del__(self):
        """Cleanup on garbage collection."""
        self.close_all()


# Convenience functions for backward compatibility
def get_pooled_connection():
    """
    Get a pooled connection.

    Returns a tuple of (connection, pool) so the caller can return the connection.
    For use with 'with' statement or manual return.

    Example:
        conn, pool = get_pooled_connection()
        try:
            # use connection
            pass
        finally:
            pool.return_connection(conn)
    """
    pool_instance = SentinelConnectionPool.get_instance()
    return pool_instance.get_connection(), pool_instance