from pipeline.source_country import resolve_country


def test_curated_generic_tld_outlet():
    assert resolve_country("https://www.reuters.com/world/article") == "GBR"
    assert resolve_country("cnn.com") == "USA"
    assert resolve_country("https://aljazeera.net/news/x") == "QAT"


def test_cctld_fallback():
    assert resolve_country("https://tass.ru/politics/1") == "RUS"
    assert resolve_country("lemonde.fr") == "FRA"
    assert resolve_country("dailymail.co.uk") == "GBR"


def test_strips_www_and_is_case_insensitive():
    assert resolve_country("HTTPS://WWW.BBC.CO.UK/news") == "GBR"


def test_unknown_generic_tld_returns_none():
    assert resolve_country("https://chinookobserver.com/local") is None
    assert resolve_country("adn.com") is None


def test_blank_returns_none():
    assert resolve_country("") is None
    assert resolve_country(None) is None


from pipeline.source_country import backfill_source_countries


class _Cur:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []
    def execute(self, q, params=None):
        self._q = q
        if "UPDATE" in q:
            self.updates.append(params)
    def fetchall(self):
        return self._rows
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return None


class _Conn:
    def __init__(self, rows):
        self.cur = _Cur(rows)
        self.committed = False
    def cursor(self):
        return self.cur
    def commit(self):
        self.committed = True


def test_backfill_updates_only_resolvable_null_country_sources():
    rows = [(1, "reuters.com"), (2, "chinookobserver.com"), (3, "tass.ru")]
    conn = _Conn(rows)
    updated = backfill_source_countries(conn)
    assert updated == 2
    assert conn.committed is True
