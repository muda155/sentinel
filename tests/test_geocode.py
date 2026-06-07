from pipeline.geocode import reverse_geocode_country


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed = (sql, params)

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._cur = _FakeCursor(row)

    def cursor(self):
        return self._cur


def test_reverse_geocode_returns_match():
    conn = _FakeConn(("FRA", "France"))
    assert reverse_geocode_country(conn, 48.85, 2.35) == ("FRA", "France")


def test_reverse_geocode_returns_none_when_no_match():
    conn = _FakeConn(None)
    assert reverse_geocode_country(conn, 0.0, 0.0) is None


def test_reverse_geocode_uses_lon_lat_order():
    conn = _FakeConn(("FRA", "France"))
    reverse_geocode_country(conn, 48.85, 2.35)
    _, params = conn._cur.executed
    assert params == (2.35, 48.85)