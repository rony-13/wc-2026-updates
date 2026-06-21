"""Tests for WorldCupService's live-refresh decision logic: detecting a
worldcup26.ir response that's *successful but stale* (still "not started"
well past kickoff) and routing to a fallback for that cycle instead of
trusting it -- this never touches the network; the real providers are
swapped out for tiny stubs after construction.

All kickoff times here are relative to the real wall clock at test-run time
(never a hardcoded date), so this suite stays correct no matter when it's
actually run.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.models import Match, SCHEDULED, LIVE, FINISHED  # noqa: E402
from app.providers import ProviderError  # noqa: E402
from app.service import WorldCupService, WORLDCUP26  # noqa: E402


class _StubProvider:
    """A fake provider: returns canned matches, or raises if told to fail."""
    def __init__(self, name, matches=None, error=None):
        self.name = name
        self._matches = matches or []
        self._error = error
        self.calls = 0

    def fetch_matches(self):
        self.calls += 1
        if self._error:
            raise ProviderError(self._error)
        return self._matches


def _service():
    """A real WorldCupService against a throwaway cache dir (uses the
    project's real seed data, but no test calls refresh() for real --
    _wc/_fallbacks get swapped for stubs before any test touches them)."""
    cfg = Config()
    cfg.CACHE_DIR = tempfile.mkdtemp()
    return WorldCupService(cfg)


def _iso(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _m(home, away, status, minutes_ago, mid="x", group="Group H", hs=None, as_=None):
    return Match(
        id=mid, group=group, stage="GROUP_STAGE", utc_date=_iso(minutes_ago),
        status=status, home=home, away=away, home_score=hs, away_score=as_,
    )


def test_fresh_not_started_within_grace_is_trusted_not_stale():
    svc = _service()
    matches = [_m("Spain", "Saudi Arabia", SCHEDULED, minutes_ago=10)]
    assert svc._find_stale_not_started(matches, datetime.now(timezone.utc)) == []


def test_not_started_past_grace_is_flagged_stale():
    svc = _service()
    matches = [_m("Spain", "Saudi Arabia", SCHEDULED, minutes_ago=30)]
    stale = svc._find_stale_not_started(matches, datetime.now(timezone.utc))
    assert stale == ["Spain vs Saudi Arabia"]


def test_live_or_finished_matches_are_never_flagged_stale():
    svc = _service()
    matches = [
        _m("Spain", "Saudi Arabia", LIVE, minutes_ago=105, hs=1, as_=0),
        _m("Belgium", "Iran", FINISHED, minutes_ago=105, hs=2, as_=1),
    ]
    assert svc._find_stale_not_started(matches, datetime.now(timezone.utc)) == []


def test_long_past_window_not_flagged_even_if_still_scheduled():
    """A fixture that's been 'scheduled' for many hours is no longer being
    live-polled at all (outside MATCH_WINDOW_MINUTES) -- not this check's job."""
    svc = _service()
    matches = [_m("Spain", "Saudi Arabia", SCHEDULED, minutes_ago=500)]
    assert svc._find_stale_not_started(matches, datetime.now(timezone.utc)) == []


def test_infer_live_status_corrects_in_progress_match_from_a_source_with_no_live_concept():
    """The actual bug report: openfootball never reports LIVE (it only ever
    has SCHEDULED or FINISHED -- see openfootball.py), so a match that's
    genuinely in progress would otherwise sit there indistinguishable from
    one that simply hasn't kicked off yet. This is exactly Belgium vs Iran
    in the report: clearly underway by the clock, but the source has no way
    to say so."""
    svc = _service()
    in_progress = _m("Belgium", "Iran", SCHEDULED, minutes_ago=45, group="Group G")
    not_yet_started = _m("New Zealand", "Egypt", SCHEDULED, minutes_ago=-60, group="Group G")  # kicks off in 1h
    already_finished = _m("Spain", "Saudi Arabia", FINISHED, minutes_ago=180, hs=2, as_=1)

    matches = [in_progress, not_yet_started, already_finished]
    svc._infer_live_status(matches)

    assert in_progress.status == LIVE
    assert in_progress.home_score is None and in_progress.away_score is None  # never invents a score
    assert not_yet_started.status == SCHEDULED  # genuinely in the future -- untouched
    assert already_finished.status == FINISHED  # explicitly finished -- untouched


def test_infer_live_status_does_not_flap_right_at_kickoff():
    svc = _service()
    just_kicked_off = _m("Belgium", "Iran", SCHEDULED, minutes_ago=1, group="Group G")
    svc._infer_live_status([just_kicked_off])
    assert just_kicked_off.status == SCHEDULED  # within the 2-minute grace, left alone


def test_infer_live_status_does_not_resurrect_a_long_dead_fixture():
    """A match still SCHEDULED many hours after its kickoff isn't 'live' --
    it's just stale/outdated data, outside the normal live-match window."""
    svc = _service()
    long_stale = _m("Belgium", "Iran", SCHEDULED, minutes_ago=500, group="Group G")
    svc._infer_live_status([long_stale])
    assert long_stale.status == SCHEDULED


def test_commit_applies_live_status_inference():
    """End-to-end through _commit (not just calling the helper directly) --
    this is what actually runs on every real refresh cycle."""
    svc = _service()
    in_progress = _m("Belgium", "Iran", SCHEDULED, minutes_ago=45, group="Group G")
    svc._commit([in_progress], "openfootball", {})
    assert svc._matches[0].status == LIVE


def test_refresh_live_falls_back_when_worldcup26_response_is_stale():
    """The actual bug report: worldcup26.ir replies successfully (no
    ProviderError) but the match is stuck 'not started' long past kickoff --
    that must route to a fallback immediately, not be trusted/committed."""
    svc = _service()
    stale_match = _m("Spain", "Saudi Arabia", SCHEDULED, minutes_ago=30)
    fresh_match = _m("Spain", "Saudi Arabia", LIVE, minutes_ago=30, hs=2, as_=1)

    svc._wc = _StubProvider(WORLDCUP26, matches=[stale_match])
    svc._fallbacks = [_StubProvider("fallback", matches=[fresh_match])]

    ok = svc._refresh_live(now=0.0)
    assert ok is True
    assert svc._source == "fallback"
    assert svc._matches[0].status == LIVE
    assert svc._matches[0].home_score == 2
    assert svc._live_realtime_ok is False  # stale data must never count as "trustworthy real-time"
    assert svc._wc.calls == 1
    assert svc._fallbacks[0].calls == 1


def test_refresh_live_commits_stale_data_anyway_if_no_fallback_reachable():
    """If even the fallback fails, still show worldcup26.ir's data (better
    than nothing, and correct for every match except the stale one) -- but
    don't mark it trustworthy, so the next cycle keeps trying a fallback.
    The committed copy still gets _infer_live_status applied like any other
    commit, so the originally-stale match ends up correctly shown as LIVE
    locally even without a fallback's help -- a real bonus of that check
    running uniformly rather than only for non-worldcup26.ir sources."""
    svc = _service()
    stale_match = _m("Spain", "Saudi Arabia", SCHEDULED, minutes_ago=30)
    svc._wc = _StubProvider(WORLDCUP26, matches=[stale_match])
    svc._fallbacks = [_StubProvider("fallback", error="down")]

    ok = svc._refresh_live(now=0.0)
    assert ok is True
    assert svc._source == WORLDCUP26
    assert svc._matches[0].status == LIVE  # corrected locally by _infer_live_status
    assert svc._live_realtime_ok is False


def test_refresh_live_normal_path_unaffected_when_nothing_is_stale():
    """Sanity check: the new staleness check must not change behavior for
    the ordinary case (a genuinely live, correctly-reported match)."""
    svc = _service()
    live_match = _m("Spain", "Saudi Arabia", LIVE, minutes_ago=30, hs=1, as_=0)
    svc._wc = _StubProvider(WORLDCUP26, matches=[live_match])
    svc._fallbacks = [_StubProvider("fallback", matches=[])]

    ok = svc._refresh_live(now=0.0)
    assert ok is True
    assert svc._source == WORLDCUP26
    assert svc._live_realtime_ok is True
    assert svc._fallbacks[0].calls == 0  # never even touched


def test_refresh_live_outright_failure_path_unaffected():
    """Sanity check: when worldcup26.ir fails outright (not stale, just
    down) and we have no prior real-time data, the existing grace-period
    -> fallback path still behaves exactly as before."""
    svc = _service()
    fresh_match = _m("Spain", "Saudi Arabia", LIVE, minutes_ago=30, hs=1, as_=0)
    svc._wc = _StubProvider(WORLDCUP26, error="connection refused")
    svc._fallbacks = [_StubProvider("fallback", matches=[fresh_match])]
    svc._live_realtime_ok = False
    svc._wc_fail_since = None

    # within the grace period -> holds, no fallback yet
    ok = svc._refresh_live(now=1000.0)
    assert ok is False
    assert svc._fallbacks[0].calls == 0

    # past the grace period -> falls back
    ok = svc._refresh_live(now=1000.0 + 61)
    assert ok is True
    assert svc._source == "fallback"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
