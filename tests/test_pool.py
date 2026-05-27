"""Tests for pipeline.pool — SentinelConnectionPool and convenience functions."""

from unittest.mock import Mock, patch

import pytest

from pipeline.pool import SentinelConnectionPool, get_pooled_connection


@pytest.fixture(autouse=True)
def reset_pool_singleton():
    """Reset the singleton between tests to ensure isolation."""
    SentinelConnectionPool._instance = None
    yield
    SentinelConnectionPool._instance = None


class TestGetPooledConnection:
    """Tests for the convenience function get_pooled_connection()."""

    def test_returns_conn_and_pool_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify get_pooled_connection returns a (conn, pool) tuple."""
        fake_conn = Mock(name="connection")
        fake_pool = Mock(name="SentinelConnectionPool")
        fake_pool.get_connection.return_value = fake_conn

        monkeypatch.setattr(
            "pipeline.pool.SentinelConnectionPool.get_instance",
            Mock(return_value=fake_pool),
        )

        conn, pool_instance = get_pooled_connection()

        assert conn is fake_conn
        assert pool_instance is fake_pool
        fake_pool.get_connection.assert_called_once()

    def test_singleton_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two calls to get_pooled_connection use the same pool instance."""
        fake_pool = Mock(name="SentinelConnectionPool")
        fake_pool.get_connection.return_value = Mock(name="connection")

        # Track how many times get_instance was called
        call_count = [0]

        def side_effect():
            call_count[0] += 1
            return fake_pool

        monkeypatch.setattr(
            "pipeline.pool.SentinelConnectionPool.get_instance",
            Mock(side_effect=side_effect),
        )

        get_pooled_connection()
        get_pooled_connection()

        # get_instance was called twice (the singleton enforcement is inside
        # get_instance itself, which we mocked out; the caller calls it each time)
        assert call_count[0] == 2


class TestSentinelConnectionPool:
    """Tests for the SentinelConnectionPool class directly."""

    def test_get_instance_returns_singleton(self) -> None:
        """get_instance returns the same object on repeated calls."""
        pool1 = SentinelConnectionPool.get_instance(
            host="test_host",
            port=9999,
            database="test_db",
            user="test_user",
            password="test_pass",
        )
        pool2 = SentinelConnectionPool.get_instance()

        assert pool1 is pool2
        assert pool1._host == "test_host"

    def test_return_connection_calls_putconn(self) -> None:
        """return_connection delegates to the underlying ThreadedConnectionPool.putconn."""
        pool_instance = SentinelConnectionPool._create_uninitialized()
        fake_threaded_pool = Mock(name="ThreadedConnectionPool")
        pool_instance._pool = fake_threaded_pool
        pool_instance._initialized = True

        fake_conn = Mock(name="psycopg2_connection")
        pool_instance.return_connection(fake_conn)

        fake_threaded_pool.putconn.assert_called_once_with(fake_conn)

    def test_return_connection_does_nothing_when_pool_none(self) -> None:
        """return_connection is a no-op when _pool is None."""
        pool_instance = SentinelConnectionPool._create_uninitialized()
        fake_conn = Mock(name="psycopg2_connection")

        # Should not raise
        pool_instance.return_connection(fake_conn)

    def test_health_check_returns_healthy_when_query_succeeds(self) -> None:
        """health_check returns status=healthy when SELECT 1 passes."""
        pool_instance = SentinelConnectionPool._create_uninitialized()

        fake_cursor = Mock(name="cursor")
        fake_cursor.__enter__ = Mock(return_value=fake_cursor)
        fake_cursor.__exit__ = Mock(return_value=False)
        fake_cursor.fetchone.return_value = (1,)

        fake_conn = Mock(name="connection")
        fake_conn.cursor.return_value = fake_cursor

        fake_threaded_pool = Mock(name="ThreadedConnectionPool")
        fake_threaded_pool.getconn.return_value = fake_conn

        pool_instance._pool = fake_threaded_pool
        pool_instance._initialized = True

        result = pool_instance.health_check()

        assert result["status"] == "healthy"
        assert result["connection_test"] is True
        assert result["pool_stats"]["initialized"] is True
        fake_cursor.execute.assert_called_once_with("SELECT 1 AS healthy")
        fake_threaded_pool.putconn.assert_called_once_with(fake_conn)

    def test_health_check_returns_not_initialized_when_pool_none(self) -> None:
        """health_check returns not_initialized when _pool is None."""
        pool_instance = SentinelConnectionPool._create_uninitialized()

        # Override _ensure_initialized to be a no-op so it doesn't
        # try to connect to a real database.
        pool_instance._ensure_initialized = lambda: None

        result = pool_instance.health_check()

        assert result["status"] == "not_initialized"
        assert result["connection_test"] is None

    def test_close_all_resets_state(self) -> None:
        """close_all closes the pool and resets _initialized."""
        pool_instance = SentinelConnectionPool._create_uninitialized()
        fake_threaded_pool = Mock(name="ThreadedConnectionPool")
        pool_instance._pool = fake_threaded_pool
        pool_instance._initialized = True

        pool_instance.close_all()

        fake_threaded_pool.closeall.assert_called_once()
        assert pool_instance._pool is None
        assert not pool_instance._initialized

    # --- helpers ---

    @staticmethod
    def _create_uninitialized() -> SentinelConnectionPool:
        """Create a SentinelConnectionPool bypassing get_instance singleton."""
        return SentinelConnectionPool(
            host="test_host",
            port=9999,
            database="test_db",
            user="test_user",
            password="test_pass",
        )


# Patch the helper onto the class so tests can create fresh instances
SentinelConnectionPool._create_uninitialized = staticmethod(
    TestSentinelConnectionPool._create_uninitialized
)
