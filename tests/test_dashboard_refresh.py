"""Tests for dashboard refresh mechanisms (auto-refresh and manual)."""

import time
from unittest.mock import MagicMock, patch


class TestRefreshIntervalLogic:
    """Test auto-refresh interval mechanism."""

    def test_should_refresh_returns_true_on_first_call(self):
        """First time running should always trigger refresh."""
        from frontend.refresh_utils import should_refresh
        
        result = should_refresh(last_refresh_time=None, interval_minutes=15)
        assert result is True

    def test_should_refresh_returns_true_after_interval_elapsed(self):
        """Should refresh when interval time has elapsed since last refresh."""
        from frontend.refresh_utils import should_refresh
        
        # Last refresh was 20 minutes ago
        last_refresh = time.time() - (20 * 60)
        result = should_refresh(last_refresh_time=last_refresh, interval_minutes=15)
        assert result is True

    def test_should_refresh_returns_false_before_interval_elapsed(self):
        """Should NOT refresh when interval time has NOT elapsed."""
        from frontend.refresh_utils import should_refresh
        
        # Last refresh was 5 minutes ago
        last_refresh = time.time() - (5 * 60)
        result = should_refresh(last_refresh_time=last_refresh, interval_minutes=15)
        assert result is False

    def test_should_refresh_respects_custom_interval(self):
        """Should respect custom interval values."""
        from frontend.refresh_utils import should_refresh
        
        # Last refresh was 10 minutes ago
        last_refresh = time.time() - (10 * 60)
        
        # With 5-minute interval, should refresh
        assert should_refresh(last_refresh_time=last_refresh, interval_minutes=5) is True
        
        # With 15-minute interval, should NOT refresh
        assert should_refresh(last_refresh_time=last_refresh, interval_minutes=15) is False


class TestManualRefreshTrigger:
    """Test manual refresh button trigger mechanism."""

    def test_trigger_manual_refresh_updates_last_refresh_time(self):
        """Calling trigger_manual_refresh should update last refresh timestamp."""
        from frontend.refresh_utils import trigger_manual_refresh
        
        before_time = time.time()
        result = trigger_manual_refresh()
        after_time = time.time()
        
        assert isinstance(result, float)
        assert before_time <= result <= after_time

    def test_last_refresh_timestamp_is_current_unix_time(self):
        """Last refresh timestamp should be Unix epoch time."""
        from frontend.refresh_utils import trigger_manual_refresh
        
        result = trigger_manual_refresh()
        
        # Should be a reasonable Unix timestamp (within last year and next year)
        now = time.time()
        one_year_ago = now - (365 * 24 * 60 * 60)
        one_year_future = now + (365 * 24 * 60 * 60)
        
        assert one_year_ago <= result <= one_year_future


class TestRefreshStateManagement:
    """Test session state management for refresh tracking."""

    @patch('streamlit.session_state', new_callable=MagicMock)
    def test_initialize_refresh_state_sets_defaults(self, mock_session_state):
        """Initialize refresh state should set default values."""
        from frontend.refresh_utils import initialize_refresh_state
        
        initialize_refresh_state(mock_session_state)
        
        # Should have set last_refresh and refresh_in_progress
        mock_session_state.__setitem__.assert_any_call('last_refresh', None)
        mock_session_state.__setitem__.assert_any_call('refresh_in_progress', False)

    @patch('streamlit.session_state', new_callable=MagicMock)
    def test_initialize_refresh_state_idempotent(self, mock_session_state):
        """Initialize refresh state should be safe to call multiple times."""
        from frontend.refresh_utils import initialize_refresh_state
        
        # Should not raise even if called twice
        initialize_refresh_state(mock_session_state)
        initialize_refresh_state(mock_session_state)
        
        # Should have been called at least twice
        assert mock_session_state.__setitem__.call_count >= 2


class TestAutoRefreshLogic:
    """Test auto-refresh logic integration."""

    def test_check_and_auto_refresh_returns_timestamp_when_refresh_needed(self):
        """check_and_auto_refresh should return timestamp when refresh is needed."""
        from frontend.refresh_utils import check_and_auto_refresh
        
        # No prior refresh
        result = check_and_auto_refresh(last_refresh_time=None, interval_minutes=15)
        assert isinstance(result, float)
        assert result > 0

    def test_check_and_auto_refresh_returns_none_when_refresh_not_needed(self):
        """check_and_auto_refresh should return None when refresh not needed."""
        from frontend.refresh_utils import check_and_auto_refresh
        
        # Last refresh was 5 minutes ago (interval is 15)
        last_refresh = time.time() - (5 * 60)
        result = check_and_auto_refresh(last_refresh_time=last_refresh, interval_minutes=15)
        assert result is None

    def test_check_and_auto_refresh_updates_timestamp_when_refreshed(self):
        """When auto-refresh occurs, timestamp should be updated."""
        from frontend.refresh_utils import check_and_auto_refresh
        
        # Force a refresh by using no prior time
        before_call = time.time()
        new_refresh_time = check_and_auto_refresh(last_refresh_time=None, interval_minutes=15)
        after_call = time.time()
        
        # Should return a Unix timestamp
        assert isinstance(new_refresh_time, float)
        assert before_call <= new_refresh_time <= after_call
