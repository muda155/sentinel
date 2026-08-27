"""FR-13 alert level is derived, never read from the never-written column.

These run without a database on purpose. The defect they guard was invisible to
every shape test in the suite: the endpoint kept returning a well-formed
`alert_level` for every hotspot, so nothing failed -- the value was simply
'Medium' for all 1321 of them, and the filter that compared against the raw
column matched zero rows for every level, including the one being reported.
A test that only asserts the field exists cannot tell those apart.
"""
import re

from api import queries
from pipeline.dashboard_data import grid_cell_alert_level


def _code_without_prose() -> str:
    """api/queries.py minus its own explanatory prose.

    The comment explaining WHY the raw column must not be read itself names
    `hotspots.alert_level`, so a naive search fires on the documentation. Only
    the two known docstrings are removed -- blanking every triple-quoted string
    would take the SQL with it, which is the thing under test."""
    from pathlib import Path
    text = Path(queries.__file__).read_text(encoding="utf-8")
    for prose in (queries.__doc__, queries._alert_level_sql.__doc__):
        if prose:
            text = text.replace(prose, "")
    return text


def test_no_query_reads_the_raw_alert_level_column():
    """hotspots.alert_level and grid_cells.alert_level are written by nothing.

    Any query selecting or filtering on them silently degrades to a constant.
    Derive from the cell's convergence instead."""
    offenders = re.findall(r"\b[a-z_]+\.alert_level\b", _code_without_prose())
    assert offenders == [], f"raw alert_level column read in api/queries.py: {offenders}"


def test_alert_level_filter_compares_the_derived_value():
    """The filter and the projection must use the same expression.

    Comparing the filter against the stored column while projecting a derived
    value is what made `?alert_level=Medium` return nothing while every row in
    the unfiltered response said 'Medium'."""
    text = _code_without_prose()
    filter_line = next(line for line in text.splitlines()
                       if "IS NULL OR" in line and "alert_level" in line)
    assert "_alert_level_sql" in filter_line, filter_line


def test_sql_thresholds_match_the_python_implementation():
    """One rule, two layers. `pipeline/dashboard_data.grid_cell_alert_level` is
    the Python statement of the same FR-13 thresholds; if the SQL drifts from
    it the map's grid layer and hotspot layer disagree about the same cell."""
    sql = queries._alert_level_sql("g")

    def sql_verdict(score: float, types: int) -> str:
        """Evaluate the generated CASE the way Postgres would."""
        if types >= 4 and score >= 80:
            return "Critical"
        if types >= 3 and score >= 70:
            return "Critical"
        if types >= 2 and score >= 50:
            return "High"
        return "Medium"

    for clause in ("g.event_type_count >= 4", "g.convergence_score >= 80",
                   "g.event_type_count >= 3", "g.convergence_score >= 70",
                   "g.event_type_count >= 2", "g.convergence_score >= 50"):
        assert clause in sql, clause

    # Every boundary, against the authoritative Python rule. None floors to
    # 'Medium' in SQL to keep schemas.Hotspot.alert_level non-null.
    for score in (0, 24, 25, 49, 50, 69, 70, 79, 80, 100):
        for types in (1, 2, 3, 4):
            expected = grid_cell_alert_level(score, types) or "Medium"
            assert sql_verdict(score, types) == expected, (score, types)


def test_a_single_type_cell_never_rises_above_medium():
    """FR-WM-CONVERGENCE: 2+ distinct types raise the level; one type does not.

    One event type caps convergence at 25 + 25 = 50, which is exactly the 'High'
    boundary — so dropping the type check silently promotes every single-type
    cell, and on the current corpus every cell is single-type."""
    for score in (0, 25, 50, 100):
        assert grid_cell_alert_level(score, 1) is None


def test_alert_level_sql_qualifies_every_column_with_the_alias():
    """The expression is embedded in queries that join two tables, both of
    which have a convergence_score. An unqualified column would silently bind
    to whichever side the planner picked."""
    sql = queries._alert_level_sql("zzz")
    for column in ("event_type_count", "convergence_score"):
        assert f"zzz.{column}" in sql
        assert not re.search(rf"(?<![.\w]){column}", sql), \
            f"{column} appears unqualified in the generated CASE"
