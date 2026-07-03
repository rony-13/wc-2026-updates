"""Regression tests for the openfootball fallback provider.

Covers two related bugs found after the worldcup26.ir penalty-shootout
fix: the openfootball feed encodes penalty-shootout scores under the "p"
key (not the "home_penalty_score"/"away_penalty_score" names used by
worldcup26.ir) and extra-time results under "et" as a *cumulative*
score -- both of which the provider previously ignored entirely.
"""
from unittest.mock import patch

from app.models import FINISHED, SCHEDULED
from app.providers.openfootball import OpenFootballProvider


def _payload(matches):
    return {"matches": matches}


def _fetch(matches):
    provider = OpenFootballProvider()
    with patch("app.providers.openfootball.requests.get") as mock_get:
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json = lambda: _payload(matches)
        return provider.fetch_matches()


def test_penalty_shootout_score_is_parsed_from_p_key():
    matches = _fetch([{
        "num": 73, "team1": "Germany", "team2": "Paraguay",
        "date": "2026-06-30", "time": "18:00 UTC+0",
        "score": {"ht": [0, 0], "ft": [1, 1], "et": [1, 1], "p": [5, 4]},
    }])
    m = matches[0]
    assert m.status == FINISHED
    assert (m.home_score, m.away_score) == (1, 1)
    assert (m.home_penalty_score, m.away_penalty_score) == (5, 4)


def test_extra_time_score_is_final_result_not_full_time_score():
    # 1-1 at 90', but 2-1 after extra time -- should NOT look like a
    # penalty-decided tie, since it was decided in extra time.
    matches = _fetch([{
        "num": 74, "team1": "Croatia", "team2": "England",
        "date": "2026-06-30", "time": "18:00 UTC+0",
        "score": {"ht": [0, 1], "ft": [1, 1], "et": [2, 1]},
    }])
    m = matches[0]
    assert (m.home_score, m.away_score) == (2, 1)  # final result, not 90'
    assert (m.home_penalty_score, m.away_penalty_score) == (None, None)


def test_regular_full_time_result_unaffected():
    matches = _fetch([{
        "num": 1, "team1": "Mexico", "team2": "South Africa",
        "date": "2026-06-11", "time": "20:00 UTC+0",
        "score": {"ht": [1, 0], "ft": [2, 0]},
    }])
    m = matches[0]
    assert (m.home_score, m.away_score) == (2, 0)
    assert (m.home_penalty_score, m.away_penalty_score) == (None, None)


def test_scheduled_match_has_no_score_or_penalties():
    matches = _fetch([{
        "num": 5, "team1": "Brazil", "team2": "TBD",
        "date": "2026-07-05", "time": "18:00 UTC+0",
    }])
    m = matches[0]
    assert m.status == SCHEDULED
    assert (m.home_score, m.away_score) == (None, None)
    assert (m.home_penalty_score, m.away_penalty_score) == (None, None)
