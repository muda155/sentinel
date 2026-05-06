"""Utilities for dashboard refresh mechanisms (auto-refresh and manual)."""

import time
import streamlit as st


def should_refresh(last_refresh_time: float | None, interval_minutes: int = 15) -> bool:
    """
    Determine if a refresh is needed based on elapsed time since last refresh.
    
    Args:
        last_refresh_time: Unix timestamp of last refresh (or None for first run)
        interval_minutes: Minimum interval in minutes between refreshes (default 15)
    
    Returns:
        True if refresh is needed, False otherwise
    """
    if last_refresh_time is None:
        return True
    
    elapsed_seconds = time.time() - last_refresh_time
    interval_seconds = interval_minutes * 60
    
    return elapsed_seconds >= interval_seconds


def trigger_manual_refresh() -> float:
    """
    Trigger a manual refresh by returning current timestamp.
    
    Returns:
        Current Unix timestamp (time.time())
    """
    return time.time()


def initialize_refresh_state(session_state) -> None:
    """
    Initialize session state for refresh tracking.
    
    Args:
        session_state: Streamlit session state object (st.session_state)
    """
    if "last_refresh" not in session_state:
        session_state["last_refresh"] = None
    if "refresh_in_progress" not in session_state:
        session_state["refresh_in_progress"] = False


def check_and_auto_refresh(
    last_refresh_time: float | None, interval_minutes: int = 15
) -> float | None:
    """
    Check if auto-refresh is needed and return updated timestamp if so.
    
    Args:
        last_refresh_time: Unix timestamp of last refresh (or None for first run)
        interval_minutes: Minimum interval in minutes between refreshes (default 15)
    
    Returns:
        New timestamp (current time) if refresh triggered, None if refresh not needed
    """
    if should_refresh(last_refresh_time, interval_minutes):
        return trigger_manual_refresh()
    return None


def format_last_refresh_display(last_refresh_time: float | None) -> str:
    """
    Format last refresh timestamp for display to user.
    
    Args:
        last_refresh_time: Unix timestamp of last refresh (or None)
    
    Returns:
        Human-readable string for display
    """
    if last_refresh_time is None:
        return "Never"
    
    from datetime import datetime, timedelta
    
    refresh_dt = datetime.fromtimestamp(last_refresh_time)
    now = datetime.now()
    elapsed = now - refresh_dt
    
    if elapsed.total_seconds() < 60:
        return "Just now"
    elif elapsed.total_seconds() < 3600:
        minutes = int(elapsed.total_seconds() / 60)
        return f"{minutes} min ago"
    elif elapsed.total_seconds() < 86400:
        hours = int(elapsed.total_seconds() / 3600)
        return f"{hours}h ago"
    else:
        return refresh_dt.strftime("%Y-%m-%d %H:%M:%S")
