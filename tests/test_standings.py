"""Tests for the standings engine — the one piece of real business logic."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import Match, FINISHED, LIVE, SCHEDULED  # noqa: E402
from app.standings import compute_standings  # noqa: E402


def _m(group, home, away, hs, as_, status=FINISHED, mid="x"):
    return Match(
        id=mid, group=group, stage="GROUP_STAGE",
        utc_date="2026-06-18T18:00:00+00:00", status=status,
        home=home, away=away, home_score=hs, away_score=as_,
    )


def test_points_and_ranking():
    matches = [
        _m("Group A", "Mexico", "South Africa", 2, 0),
        _m("Group A", "South Korea", "Czechia", 2, 1),
        _m("Group A", "Mexico", "South Korea", 1, 1),
        _m("Group A", "Czechia", "South Africa", 0, 0),
    ]
    table = compute_standings(matches)["Group A"]
    by_team = {r.team: r for r in table}
    assert by_team["Mexico"].points == 4      # win + draw
    assert by_team["South Korea"].points == 4  # win + draw
    # Mexico ahead on goal difference (+2 vs +1)
    assert by_team["Mexico"].rank == 1
    assert by_team["South Korea"].rank == 2
    assert by_team["Mexico"].qualifies and by_team["South Korea"].qualifies
    assert not by_team["Czechia"].qualifies


def test_top_two_flagged_per_group():
    table = compute_standings([_m("Group B", "A", "B", 3, 0)])
    flagged = [r for r in table["Group B"] if r.qualifies]
    assert len(flagged) == 2  # exactly the top two, even with one match played


def test_live_match_counts_toward_table():
    live = _m("Group C", "X", "Y", 1, 0, status=LIVE)
    row = {r.team: r for r in compute_standings([live])["Group C"]}
    assert row["X"].points == 3   # live score already moves the table
    assert row["X"].played == 1


def test_scheduled_match_is_ignored():
    sched = _m("Group D", "P", "Q", None, None, status=SCHEDULED)
    row = {r.team: r for r in compute_standings([sched])["Group D"]}
    assert row["P"].played == 0
    assert row["P"].points == 0


def test_knockout_matches_excluded():
    ko = Match(id="k", group=None, stage="LAST_32",
               utc_date="2026-06-28T18:00:00+00:00", status=FINISHED,
               home="2A", away="2B", home_score=1, away_score=0)
    assert compute_standings([ko]) == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
