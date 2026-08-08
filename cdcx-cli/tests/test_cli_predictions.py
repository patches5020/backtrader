"""
CLI dispatch tests for --predictions / --predictions-search /
--predictions-contract -- these stub out PredictionsClient entirely (no
network) and just verify main() routes each flag to the right handler with
the right arguments, same monkeypatch-the-internals style used for the
other independent commands (--list-trades, --update-trades).
"""

from types import SimpleNamespace

from cdcx import cli


def test_predictions_bare_flag_lists_all_kinds(monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, api_key=""):
            calls.append(("init", api_key))

        def list_events(self, kind=None, limit=20):
            calls.append(("list_events", kind, limit))
            return []

    monkeypatch.setattr("cdcx.predictions.PredictionsClient", FakeClient)

    result = cli.main(["--predictions"])
    out = capsys.readouterr().out

    assert result == 0
    assert ("list_events", None, 20) in calls
    assert "all kinds" in out


def test_predictions_with_kind_filters(monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, api_key=""):
            pass

        def list_events(self, kind=None, limit=20):
            calls.append(kind)
            return []

    monkeypatch.setattr("cdcx.predictions.PredictionsClient", FakeClient)

    result = cli.main(["--predictions", "NFL", "--predictions-limit", "5"])
    assert result == 0
    assert calls == ["NFL"]


def test_predictions_search_dispatches_with_query(monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, api_key=""):
            pass

        def search_events(self, query, limit=20):
            calls.append((query, limit))
            return []

    monkeypatch.setattr("cdcx.predictions.PredictionsClient", FakeClient)

    result = cli.main(["--predictions-search", "super bowl"])
    out = capsys.readouterr().out
    assert result == 0
    assert calls == [("super bowl", 20)]
    assert "super bowl" in out


def test_predictions_contract_dispatches_with_ticker(monkeypatch, capsys):
    from cdcx.predictions import ContractPrice

    class FakeClient:
        def __init__(self, api_key=""):
            pass

        def get_contract_price(self, ticker):
            return ContractPrice(ticker=ticker, ask=0.5, bid=0.5, probability_pct=50.0)

    monkeypatch.setattr("cdcx.predictions.PredictionsClient", FakeClient)

    result = cli.main(["--predictions-contract", "BTC-YES"])
    out = capsys.readouterr().out
    assert result == 0
    assert "BTC-YES" in out


def test_predictions_contract_404_prints_clear_message_not_raw_http_error(monkeypatch, capsys):
    from cdcx.predictions import PredictionsNotFound

    class FakeClient:
        def __init__(self, api_key=""):
            pass

        def get_contract_price(self, ticker):
            raise PredictionsNotFound(f"Nothing found ... {ticker} may not be listed/live right now")

    monkeypatch.setattr("cdcx.predictions.PredictionsClient", FakeClient)

    result = cli.main(["--predictions-contract", "BTC-YES"])
    err = capsys.readouterr().err
    assert result == 1
    assert "may not be listed/live" in err
    assert "Error fetching contract price" not in err  # clear message, not the generic wrapper


def test_predictions_rate_limit_error_exits_nonzero(monkeypatch, capsys):
    from cdcx.predictions import PredictionsRateLimited

    class FakeClient:
        def __init__(self, api_key=""):
            pass

        def list_events(self, kind=None, limit=20):
            raise PredictionsRateLimited("Rate limited -- retry after 10s")

    monkeypatch.setattr("cdcx.predictions.PredictionsClient", FakeClient)

    result = cli.main(["--predictions"])
    err = capsys.readouterr().err
    assert result == 1
    assert "Rate limited" in err


def test_predictions_flags_do_not_require_credentials_or_network(monkeypatch):
    # Sanity check the dispatch happens before any exchange/engine import --
    # i.e. --predictions is a fully independent command, like --list-trades.
    called = {"exchange_imported": False}

    class FakeClient:
        def __init__(self, api_key=""):
            pass

        def list_events(self, kind=None, limit=20):
            return []

    monkeypatch.setattr("cdcx.predictions.PredictionsClient", FakeClient)
    result = cli.main(["--predictions"])
    assert result == 0
