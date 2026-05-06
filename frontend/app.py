"""Streamlit dashboard for Sentinel OSINT hotspot visualization."""

from __future__ import annotations

import streamlit as st
import pydeck as pdk
import pandas as pd
import time
from pipeline.dashboard_data import confidence_to_color, fetch_dashboard_hotspots
from pipeline.db import get_connection
from frontend.refresh_utils import (
    initialize_refresh_state,
    should_refresh,
    trigger_manual_refresh,
    format_last_refresh_display,
)


def format_hotspots_for_pydeck(hotspots: list[dict]) -> list[dict]:
    """
    Format hotspots for pydeck rendering with color column.
    
    Args:
        hotspots: List of hotspot dictionaries from fetch_dashboard_hotspots()
    
    Returns:
        List of hotspot dicts with pydeck-compatible color column [R, G, B, A]
    """
    formatted = []
    for hotspot in hotspots:
        spot = hotspot.copy()
        spot["color"] = confidence_to_color(hotspot.get("conf_score", 0))
        formatted.append(spot)
    return formatted


def get_confidence_category(conf_score: float) -> str:
    """
    Classify confidence score into category.
    
    Args:
        conf_score: Confidence score (0-100)
    
    Returns:
        Category: "High" (>70), "Medium" (40-70), or "Low" (<40)
    """
    score = float(conf_score or 0)
    if score > 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def extract_sitrep_details(hotspot: dict) -> dict:
    """
    Extract SITREP (Situation Report) details from a hotspot.
    
    Args:
        hotspot: Hotspot dictionary
    
    Returns:
        Dict with: conflict_type, key_locations, participants, confidence, 
        confidence_category, timestamp, llm_summary, event_count
    """
    conf_score = hotspot.get("conf_score", 0)
    
    return {
        "conflict_type": "Conflict" if hotspot.get("conflict_detected") else "No Conflict",
        "key_locations": f"({hotspot.get('latitude', 0):.2f}, {hotspot.get('longitude', 0):.2f})",
        "participants": "Unknown",
        "confidence": conf_score,
        "confidence_category": get_confidence_category(conf_score),
        "timestamp": f"{hotspot.get('start_window', '')} to {hotspot.get('end_window', '')}",
        "llm_summary": hotspot.get("summary_text", "No summary available"),
        "event_count": hotspot.get("event_count", 0),
    }


def build_map_config(formatted_hotspots: list[dict]) -> dict:
    """
    Build pydeck map configuration with hotspot layer.
    
    Args:
        formatted_hotspots: List of formatted hotspots with color column
    
    Returns:
        Dict with viewport and layers for pydeck rendering
    """
    # Calculate center: use mean lat/lon if hotspots exist, else default world view
    if formatted_hotspots:
        lats = [h.get("latitude", 0) for h in formatted_hotspots]
        lons = [h.get("longitude", 0) for h in formatted_hotspots]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
    else:
        # Default to world center
        center_lat = 20
        center_lon = 10

    viewport = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=3,
        pitch=0,
    )

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=formatted_hotspots,
        pickable=True,
        opacity=0.8,
        stroked=True,
        filled=True,
        radius_scale=15,
        radius_min_pixels=5,
        radius_max_pixels=60,
        line_width_min_pixels=1,
        get_position=["longitude", "latitude"],
        get_fill_color="color",
        get_line_color=[255, 255, 255],
        get_radius="event_count",
    )

    return {
        "viewport": {
            "latitude": viewport.latitude,
            "longitude": viewport.longitude,
            "zoom": viewport.zoom,
            "pitch": viewport.pitch,
        },
        "layers": [layer],
    }


def render_dashboard():
    """Main Streamlit dashboard application."""
    st.set_page_config(
        page_title="Sentinel OSINT Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Dark theme styling
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background-color: #1a1a1a;
        }
        [data-testid="stSidebar"] {
            background-color: #0d0d0d;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Initialize session state for selected hotspot and refresh tracking
    if "selected_hotspot" not in st.session_state:
        st.session_state.selected_hotspot = None
    
    initialize_refresh_state(st.session_state)

    # Title
    st.title("🛰️ Sentinel OSINT Dashboard")
    st.subheader("Real-time Geopolitical Threat Monitoring")

    # Sidebar controls: Manual refresh and status
    with st.sidebar:
        st.markdown("### 🔄 Refresh Controls")
        
        # Manual refresh button
        if st.button("🔄 Refresh Now", use_container_width=True):
            st.session_state["last_refresh"] = trigger_manual_refresh()
            st.session_state["refresh_in_progress"] = True
            st.rerun()
        
        # Display last refresh time
        refresh_time_text = format_last_refresh_display(st.session_state.get("last_refresh"))
        st.text(f"Last refresh: {refresh_time_text}")
        st.text(f"Auto-refresh interval: 15 minutes")
        
        st.markdown("---")

    try:
        # Check if auto-refresh is needed (15-minute interval)
        auto_refresh_needed = should_refresh(
            st.session_state.get("last_refresh"),
            interval_minutes=15
        )
        
        if auto_refresh_needed and not st.session_state.get("refresh_in_progress", False):
            st.session_state["last_refresh"] = trigger_manual_refresh()

        # Fetch hotspots from database
        conn = get_connection()
        hotspots = fetch_dashboard_hotspots(conn, limit=100)
        conn.close()
        
        # Mark refresh as complete
        st.session_state["refresh_in_progress"] = False

        if not hotspots:
            st.warning("No hotspots found in database.")
            return

        # Format hotspots for pydeck
        formatted_hotspots = format_hotspots_for_pydeck(hotspots)

        # Create layout: map (70%) + sidebar (30%)
        col1, col2 = st.columns([0.70, 0.30])

        with col1:
            st.subheader("📍 Hotspot Map")
            
            # Convert formatted hotspots to DataFrame for pydeck
            df = pd.DataFrame(formatted_hotspots)
            
            # Build map configuration
            map_config = build_map_config(formatted_hotspots)
            viewport = pdk.ViewState(
                latitude=map_config["viewport"]["latitude"],
                longitude=map_config["viewport"]["longitude"],
                zoom=map_config["viewport"]["zoom"],
            )
            
            # Create and display map
            deck = pdk.Deck(
                map_style="mapbox://styles/mapbox/dark-v10",
                initial_view_state=viewport,
                layers=map_config["layers"],
                tooltip={
                    "html": "<b>Event Count:</b> {event_count} "
                            "<br/><b>Confidence:</b> {conf_score}% "
                            "<br/><b>Category:</b> "
                            "{start_window} to {end_window}",
                    "style": {"backgroundColor": "steelblue", "color": "white"},
                },
            )
            st.pydeck_chart(deck)

        with col2:
            st.subheader("📋 SITREP Details")
            
            # Hotspot selector
            hotspot_labels = [
                f"Hotspot {h.get('hotspot_id')} "
                f"(Conf: {h.get('conf_score', 0):.0f}%)"
                for h in hotspots
            ]
            selected_idx = st.selectbox("Select hotspot:", range(len(hotspots)), 
                                       format_func=lambda i: hotspot_labels[i])
            
            if selected_idx is not None:
                selected_hotspot = hotspots[selected_idx]
                sitrep = extract_sitrep_details(selected_hotspot)
                
                st.session_state.selected_hotspot = selected_hotspot

                # Display SITREP details with high-contrast styling
                st.markdown("---")
                st.markdown(f"**Conflict Type:** {sitrep['conflict_type']}")
                st.markdown(f"**Confidence:** {sitrep['confidence']:.0f}% ({sitrep['confidence_category']})")
                st.markdown(f"**Location:** {sitrep['key_locations']}")
                st.markdown(f"**Events:** {sitrep['event_count']}")
                st.markdown(f"**Time Window:** {sitrep['timestamp']}")
                st.markdown("---")
                st.markdown(f"**Summary:**\n\n{sitrep['llm_summary']}")

        # Statistics footer
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Hotspots", len(hotspots))
        with col2:
            high_conf = len([h for h in hotspots if h.get("conf_score", 0) > 70])
            st.metric("High Confidence", high_conf)
        with col3:
            total_events = sum(h.get("event_count", 0) for h in hotspots)
            st.metric("Total Events", total_events)

    except Exception as e:
        st.error(f"Error loading dashboard: {str(e)}")


if __name__ == "__main__":
    render_dashboard()
