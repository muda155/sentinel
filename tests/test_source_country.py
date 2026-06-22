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
