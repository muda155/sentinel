from datetime import date

from pipeline.retention import months_to_provision, partitions_to_drop


def test_months_to_provision_includes_current_and_ahead():
    got = months_to_provision(today=date(2026, 6, 7), ahead=3)
    assert got == ["2026_06", "2026_07", "2026_08", "2026_09"]


def test_months_to_provision_rolls_over_year():
    got = months_to_provision(today=date(2026, 11, 15), ahead=3)
    assert got == ["2026_11", "2026_12", "2027_01", "2027_02"]


def test_partitions_to_drop_selects_only_expired():
    existing = ["events_2026_01", "events_2026_02", "events_2026_06"]
    got = partitions_to_drop(existing, keep_from=date(2026, 3, 1))
    assert got == ["events_2026_01", "events_2026_02"]


def test_partitions_to_drop_ignores_non_partition_names():
    existing = ["events", "events_new", "events_2026_01"]
    got = partitions_to_drop(existing, keep_from=date(2026, 6, 1))
    assert got == ["events_2026_01"]