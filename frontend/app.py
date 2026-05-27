"""Streamlit dashboard for Sentinel OSINT hotspot visualization."""

from __future__ import annotations

import streamlit as st
import pydeck as pdk
import pandas as pd
import json
from pipeline.dashboard_data import (
    confidence_to_color,
    alert_to_ring_color,
    grid_cell_alert_color,
    fetch_dashboard_hotspots,
    fetch_grid_cells_for_overlay,
)
from pipeline.db import get_pooled_connection
from frontend.refresh_utils import (
    initialize_refresh_state,
    should_refresh,
    trigger_manual_refresh,
    format_last_refresh_display,
)

# Vietnamese translations
TRANSLATIONS = {
    "en": {
        "title": "Sentinel OSINT Dashboard",
        "subtitle": "Real-time Geopolitical Threat Monitoring",
        "refresh_controls": "Refresh Controls",
        "refresh_now": "Refresh Now",
        "last_refresh": "Last refresh",
        "auto_refresh_interval": "Auto-refresh interval",
        "minutes": "minutes",
        "hotspot_map": "Hotspot Map",
        "sitrep_details": "SITREP Details",
        "select_hotspot": "Select hotspot",
        "conflict_type": "Conflict Type",
        "conflict": "Conflict",
        "no_conflict": "No Conflict",
        "confidence": "Confidence",
        "convergence": "Convergence",
        "alert_level": "Alert Level",
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "location": "Location",
        "events": "Events",
        "time_window": "Time Window",
        "summary": "Summary",
        "no_summary": "No summary available",
        "no_hotspots": "No hotspots found in database.",
        "high_confidence": "High Confidence",
        "total_hotspots": "Total Hotspots",
        "total_events": "Total Events",
        "language": "Language",
        "grid_overlay": "Show Grid-Cell Overlay",
        "na": "N/A",
    },
    "vi": {
        "title": "Bảng Điều Khiển OSINT Sentinel",
        "subtitle": "Giám Sát Đe Dọa Địa-Chính Trị Thời Gian Thực",
        "refresh_controls": "Điều Khiển Làm Mới",
        "refresh_now": "Làm Mới Ngay",
        "last_refresh": "Lần làm mới cuối",
        "auto_refresh_interval": "Khoảng làm mới tự động",
        "minutes": "phút",
        "hotspot_map": "Bản Đồ Điểm Nóng",
        "sitrep_details": "Chi Tiết SITREP",
        "select_hotspot": "Chọn điểm nóng",
        "conflict_type": "Loại Xung Đột",
        "conflict": "Xung Đột",
        "no_conflict": "Không Xung Đột",
        "confidence": "Độ Tin Cậy",
        "convergence": "Độ Hội Tụ",
        "alert_level": "Mức Cảnh Báo",
        "low": "Thấp",
        "medium": "Trung Bình",
        "high": "Cao",
        "location": "Vị Trí",
        "events": "Sự Kiện",
        "time_window": "Khoảng Thời Gian",
        "summary": "Tóm Tắt",
        "no_summary": "Không có tóm tắt",
        "no_hotspots": "Không tìm thấy điểm nóng trong cơ sở dữ liệu.",
        "high_confidence": "Độ Tin Cậy Cao",
        "total_hotspots": "Tổng Điểm Nóng",
        "total_events": "Tổng Sự Kiện",
        "language": "Ngôn Ngữ",
        "grid_overlay": "Hiển Thị Lưới Hội Tụ",
        "na": "N/A",
    },
}


def format_hotspots_for_pydeck(hotspots: list[dict]) -> list[dict]:
    """
    Format hotspots for pydeck rendering with colour and ring columns.

    Adds ``color`` (fill, based on conf_score) and ``ring_color``
    (stroke, based on alert_level) to each hotspot dict.

    Args:
        hotspots: List of hotspot dictionaries from fetch_dashboard_hotspots()

    Returns:
        List of hotspot dicts with pydeck-compatible colour columns.
    """
    formatted = []
    for hotspot in hotspots:
        spot = hotspot.copy()
        spot["color"] = confidence_to_color(hotspot.get("conf_score", 0))
        spot["ring_color"] = alert_to_ring_color(
            hotspot.get("alert_level")
        )
        formatted.append(spot)
    return formatted


def get_confidence_category(conf_score: float, locale: str = "en") -> str:
    """
    Classify confidence score into category.

    Args:
        conf_score: Confidence score (0-100)
        locale: 'en' or 'vi'

    Returns:
        Category label in the requested locale.
    """
    if locale not in TRANSLATIONS:
        locale = "en"
    score = float(conf_score or 0)
    if score > 70:
        return TRANSLATIONS[locale]["high"]
    if score >= 40:
        return TRANSLATIONS[locale]["medium"]
    return TRANSLATIONS[locale]["low"]


def _alert_level_badge(alert_level: str | None) -> str:
    """Return an HTML badge span for the alert level."""
    level = (alert_level or "Medium").strip()
    if level == "Critical":
        return (
            "<span style='background:#dc2626;color:#fff;padding:2px 8px;"
            "border-radius:4px;font-weight:bold;'>Critical</span>"
        )
    if level == "High":
        return (
            "<span style='background:#ea580c;color:#fff;padding:2px 8px;"
            "border-radius:4px;font-weight:bold;'>High</span>"
        )
    return (
        "<span style='background:#4b5563;color:#ccc;padding:2px 8px;"
        "border-radius:4px;'>Medium</span>"
    )


def extract_sitrep_details(hotspot: dict, locale: str = "en") -> dict:
    """
    Extract SITREP (Situation Report) details from a hotspot.

    Args:
        hotspot: Hotspot dictionary.
        locale: 'en' or 'vi'.

    Returns:
        Dict with conflict_type, key_locations, confidence,
        convergence_score, alert_level, confidence_category, timestamp,
        llm_summary, event_count.
    """
    if locale not in TRANSLATIONS:
        locale = "en"
    conf_score = hotspot.get("conf_score", 0)
    convergence_score = hotspot.get("convergence_score", 0)
    alert_level = hotspot.get("alert_level", "Medium")
    t = TRANSLATIONS[locale]

    return {
        "conflict_type": (
            t["conflict"]
            if hotspot.get("conflict_detected")
            else t["no_conflict"]
        ),
        "key_locations": (
            f"({hotspot.get('latitude', 0):.2f}, "
            f"{hotspot.get('longitude', 0):.2f})"
        ),
        "participants": "Unknown",
        "confidence": conf_score,
        "confidence_category": get_confidence_category(conf_score, locale),
        "convergence_score": convergence_score,
        "alert_level": alert_level,
        "alert_level_badge": _alert_level_badge(alert_level),
        "timestamp": (
            f"{hotspot.get('start_window', '')} to "
            f"{hotspot.get('end_window', '')}"
        ),
        "llm_summary": hotspot.get("summary_text", t["no_summary"]),
        "event_count": hotspot.get("event_count", 0),
    }


def build_map_config(
    formatted_hotspots: list[dict],
) -> dict:
    """
    Build pydeck map configuration with hotspot layer and alert ring layer.

    The main layer encodes conf_score as fill colour. A secondary
    ScatterplotLayer (no fill, coloured stroke) draws alert level rings
    for Critical and High alerts (FR-13).

    Args:
        formatted_hotspots: List of formatted hotspots with color and
            ring_color columns.

    Returns:
        Dict with ``viewport`` and ``layers`` keys.
    """
    # Calculate centre
    if formatted_hotspots:
        lats = [h.get("latitude", 0) for h in formatted_hotspots]
        lons = [h.get("longitude", 0) for h in formatted_hotspots]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
    else:
        center_lat = 20
        center_lon = 10

    viewport = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=3,
        pitch=0,
    )

    # Main hotspot layer — filled circles coloured by conf_score
    main_layer = pdk.Layer(
        "ScatterplotLayer",
        data=formatted_hotspots,
        pickable=True,
        opacity=0.85,
        stroked=True,
        filled=True,
        radius_scale=15,
        radius_min_pixels=5,
        radius_max_pixels=60,
        line_width_min_pixels=1,
        get_position=["longitude", "latitude"],
        get_fill_color="color",
        get_line_color=[255, 255, 255, 80],
        get_radius="event_count",
    )

    layers = [main_layer]

    # Alert ring layer — only visible for Critical/High alerts (FR-13)
    alert_hotspots = [
        h
        for h in formatted_hotspots
        if h.get("alert_level") in ("Critical", "High")
    ]
    if alert_hotspots:
        ring_layer = pdk.Layer(
            "ScatterplotLayer",
            data=alert_hotspots,
            pickable=False,
            opacity=1.0,
            stroked=True,
            filled=False,
            radius_scale=20,            # slightly larger than main layer
            radius_min_pixels=9,
            radius_max_pixels=70,
            line_width_min_pixels=3,
            get_position=["longitude", "latitude"],
            get_line_color="ring_color",
            get_radius="event_count",
        )
        layers.append(ring_layer)

    return {
        "viewport": {
            "latitude": viewport.latitude,
            "longitude": viewport.longitude,
            "zoom": viewport.zoom,
            "pitch": viewport.pitch,
        },
        "layers": layers,
    }


def _build_grid_cell_overlay_layer(
    grid_cells: list[dict],
) -> pdk.Layer | None:
    """Build a pydeck PolygonLayer for the grid-cell convergence overlay.

    Each grid cell is colour-coded by its derived alert_level.

    Args:
        grid_cells: List of grid-cell dicts from fetch_grid_cells_for_overlay().

    Returns:
        A pydeck PolygonLayer, or None if no cells to render.
    """
    if not grid_cells:
        return None

    # Parse GeoJSON geometry into pydeck-compatible polygon coordinates.
    # ST_AsGeoJSON returns a GeoJSON geometry; we extract the outer ring.
    records = []
    for cell in grid_cells:
        try:
            geom = json.loads(cell.get("geometry", "{}"))
            coords = geom.get("coordinates", [])
            if not coords or not coords[0]:
                continue
            # GeoJSON polygon: [[[lng, lat], ...]]  (outer ring first)
            polygon = coords[0]
            records.append({
                "polygon": polygon,
                "color": grid_cell_alert_color(cell.get("alert_level")),
                "convergence_score": cell.get("convergence_score", 0),
                "alert_level": cell.get("alert_level", "Medium"),
                "event_type_count": cell.get("event_type_count", 0),
            })
        except (json.JSONDecodeError, KeyError, IndexError):
            continue

    if not records:
        return None

    return pdk.Layer(
        "PolygonLayer",
        data=records,
        pickable=True,
        stroked=True,
        filled=True,
        extruded=False,
        opacity=0.35,
        get_polygon="polygon",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 50],
        line_width_min_pixels=1,
    )


def render_dashboard():
    """Main Streamlit dashboard application."""
    st.set_page_config(
        page_title="Sentinel OSINT Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Dark theme styling with light text for visibility
    st.markdown(
        """
        <style>
        /* Dark background */
        [data-testid="stAppViewContainer"] {
            background-color: #0d0d0d;
        }
        [data-testid="stSidebar"] {
            background-color: #141414;
        }
        /* Light text for visibility */
        [data-testid="stAppViewContainer"] h1,
        [data-testid="stAppViewContainer"] h2,
        [data-testid="stAppViewContainer"] h3,
        [data-testid="stAppViewContainer"] p,
        [data-testid="stAppViewContainer"] label,
        [data-testid="stAppViewContainer"] span {
            color: #e0e0e0 !important;
        }
        /* Light text in sidebar */
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label {
            color: #e0e0e0 !important;
        }
        /* Light text for metric values */
        [data-testid="stMetricValue"] {
            color: #ffffff !important;
        }
        [data-testid="stMetricLabel"] {
            color: #cccccc !important;
        }
        /* Light text for markdown */
        .stApp p, .stApp span {
            color: #e0e0e0 !important;
        }
        /* Refresh button text */
        .stButton > button {
            color: #ffffff;
            background-color: #2563eb;
        }
        /* Make map container visible */
        [data-testid="stDeckGlChart"] {
            background-color: transparent !important;
            min-height: 500px;
        }
        /* Ensure column layout works */
        [data-testid="column"] {
            background-color: transparent;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Initialize session state for selected hotspot and refresh tracking
    if "selected_hotspot" not in st.session_state:
        st.session_state.selected_hotspot = None

    initialize_refresh_state(st.session_state)

    # Language selector (sidebar)
    with st.sidebar:
        lang_options = list(TRANSLATIONS.keys())
        lang_labels = {"en": "English", "vi": "Tiếng Việt"}
        selected_lang = st.selectbox(
            "Language / Ngôn Ngữ",
            lang_options,
            format_func=lambda x: lang_labels[x],
        )
        locale = selected_lang
        t = TRANSLATIONS[locale]

    # Title
    st.title(f"🛰️ {t['title']}")
    st.subheader(t["subtitle"])

    # Sidebar controls: Manual refresh and status
    with st.sidebar:
        st.markdown(f"### 🔄 {t['refresh_controls']}")

        # Manual refresh button
        if st.button(f"🔄 {t['refresh_now']}", use_container_width=True):
            st.session_state["last_refresh"] = trigger_manual_refresh()
            st.session_state["refresh_in_progress"] = True
            st.rerun()

        # Display last refresh time
        refresh_time_text = format_last_refresh_display(
            st.session_state.get("last_refresh")
        )
        st.text(f"{t['last_refresh']}: {refresh_time_text}")
        st.text(f"{t['auto_refresh_interval']}: 15 {t['minutes']}")

        st.markdown("---")

        # Grid-cell overlay toggle (FR-13)
        show_grid_overlay = st.checkbox(
            t["grid_overlay"],
            value=False,
            help="Overlay 1x1 degree grid cells colour-coded by convergence alert level",
        )

    try:
        # Check if auto-refresh is needed (15-minute interval)
        auto_refresh_needed = should_refresh(
            st.session_state.get("last_refresh"),
            interval_minutes=15,
        )

        if auto_refresh_needed and not st.session_state.get(
            "refresh_in_progress", False
        ):
            st.session_state["last_refresh"] = trigger_manual_refresh()

        # Fetch hotspots from database
        conn, conn_pool = get_pooled_connection()
        try:
            hotspots = fetch_dashboard_hotspots(conn, limit=100)

            # Fetch grid cells for overlay if toggled on
            grid_cells = None
            if show_grid_overlay:
                grid_cells = fetch_grid_cells_for_overlay(conn)
        finally:
            conn_pool.return_connection(conn)

        # Mark refresh as complete
        st.session_state["refresh_in_progress"] = False

        if not hotspots:
            st.warning(t["no_hotspots"])
            return

        # Format hotspots for pydeck
        formatted_hotspots = format_hotspots_for_pydeck(hotspots)

        # Create layout: map (70%) + sidebar (30%)
        col1, col2 = st.columns([0.70, 0.30])

        with col1:
            st.subheader(f"\U0001f4cd {t['hotspot_map']}")

            # Build map configuration (with alert rings)
            map_config = build_map_config(formatted_hotspots)
            viewport = pdk.ViewState(
                latitude=map_config["viewport"]["latitude"],
                longitude=map_config["viewport"]["longitude"],
                zoom=map_config["viewport"]["zoom"],
            )

            all_layers = list(map_config["layers"])

            # Add grid-cell overlay layer if toggled on
            if show_grid_overlay and grid_cells:
                overlay = _build_grid_cell_overlay_layer(grid_cells)
                if overlay is not None:
                    all_layers.append(overlay)

            # Create and display map
            deck = pdk.Deck(
                map_style=pdk.map_styles.CARTO_DARK,
                initial_view_state=viewport,
                layers=all_layers,
                tooltip={
                    "html": (
                        f"<b>{t['events']}:</b> {{event_count}} "
                        f"<br/><b>{t['confidence']}:</b> {{conf_score}}% "
                        f"<br/><b>{t['convergence']}:</b> "
                        "{{convergence_score}} "
                        f"<br/><b>{t['alert_level']}:</b> {{alert_level}}"
                    ),
                    "style": {"backgroundColor": "#1e3a5f", "color": "white"},
                },
            )
            st.pydeck_chart(deck, use_container_width=True)

        with col2:
            st.subheader(f"\U0001f4cb {t['sitrep_details']}")

            # Hotspot selector
            hotspot_labels = [
                f"Hotspot {h.get('hotspot_id')} "
                f"(Conf: {h.get('conf_score', 0):.0f}%)"
                for h in hotspots
            ]
            selected_idx = st.selectbox(
                f"{t['select_hotspot']}:",
                range(len(hotspots)),
                format_func=lambda i: hotspot_labels[i],
            )

            if selected_idx is not None:
                selected_hotspot = hotspots[selected_idx]
                sitrep = extract_sitrep_details(selected_hotspot, locale)

                st.session_state.selected_hotspot = selected_hotspot

                # Display SITREP details with high-contrast styling
                st.markdown("---")
                st.markdown(
                    f"**{t['conflict_type']}:** {sitrep['conflict_type']}"
                )
                st.markdown(
                    f"**{t['confidence']} (Consensus):** "
                    f"{sitrep['confidence']:.0f}% "
                    f"({sitrep['confidence_category']})"
                )
                st.markdown(
                    f"**{t['convergence']} (Convergence):** "
                    f"{sitrep['convergence_score']:.0f}"
                )
                st.markdown(
                    f"**{t['alert_level']}:** "
                    f"{sitrep['alert_level_badge']}",
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{t['location']}:** {sitrep['key_locations']}")
                st.markdown(f"**{t['events']}:** {sitrep['event_count']}")
                st.markdown(
                    f"**{t['time_window']}:** {sitrep['timestamp']}"
                )
                st.markdown("---")
                st.markdown(
                    f"**{t['summary']}:**\n\n{sitrep['llm_summary']}"
                )

        # Statistics footer
        st.markdown("---")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric(t["total_hotspots"], len(hotspots))
        with col_b:
            high_conf = len(
                [h for h in hotspots if h.get("conf_score", 0) > 70]
            )
            st.metric(t["high_confidence"], high_conf)
        with col_c:
            total_events = sum(
                h.get("event_count", 0) for h in hotspots
            )
            st.metric(t["total_events"], total_events)

    except Exception as e:
        st.error(f"Error loading dashboard: {str(e)}")


if __name__ == "__main__":
    render_dashboard()
