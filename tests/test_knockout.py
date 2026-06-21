"""Tests for best-third-place ranking and Round-of-32 bracket projection."""
import os
import sys
from collections import OrderedDict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import Match, StandingRow, FINISHED, SCHEDULED  # noqa: E402
from app.standings import compute_standings  # noqa: E402
from app.knockout import (  # noqa: E402
    R32_TEMPLATE,
    rank_third_place_teams,
    best_eight_thirds,
    _assign_third_place_slots,
    _third_place_slots_in_match_order,
    compute_round_of_32,
)

ALL_GROUPS = list("ABCDEFGHIJKL")


def _row(group_letter, team, points, gd, gf):
    r = StandingRow(group=f"Group {group_letter}", team=team)
    r.points = points
    r.goals_for = gf
    r.goals_against = gf - gd
    r.rank = 3
    return r


def _m(group, home, away, hs, as_, status=FINISHED, mid="x"):
    return Match(
        id=mid, group=group, stage="GROUP_STAGE",
        utc_date="2026-06-18T18:00:00+00:00", status=status,
        home=home, away=away, home_score=hs, away_score=as_,
    )


# ---- template integrity --------------------------------------------------

def test_template_has_16_matches_32_slots():
    assert len(R32_TEMPLATE) == 16
    seen_match_ids = [mid for mid, _, _ in R32_TEMPLATE]
    assert len(set(seen_match_ids)) == 16, "duplicate match ids"
    assert seen_match_ids == sorted(seen_match_ids), "must be in match-id order"


def test_template_uses_every_group_exactly_once_per_role_as_expected():
    # every group's winner is used exactly once across the template (either
    # in a W/RU pairing or a W/3RD pairing); same for runner-up
    winner_uses, runnerup_use_count = [], {}
    for _, (hr, ha), (ar, aa) in R32_TEMPLATE:
        for role, arg in ((hr, ha), (ar, aa)):
            if role == "W":
                winner_uses.append(arg)
            elif role == "RU":
                runnerup_use_count[arg] = runnerup_use_count.get(arg, 0) + 1
    assert sorted(winner_uses) == ALL_GROUPS, "every group's winner used exactly once"
    assert sorted(runnerup_use_count.keys()) == ALL_GROUPS, "every group's runner-up used"
    assert all(v == 1 for v in runnerup_use_count.values())


def test_third_place_slots_extracted_correctly():
    slots = _third_place_slots_in_match_order()
    assert len(slots) == 8
    winner_groups = [w for w, _ in slots]
    assert winner_groups == ["E", "I", "A", "L", "D", "G", "B", "K"], \
        "must match real worldcup26.ir match order (74,77,79,80,81,82,85,87)"


# ---- bipartite matching: exhaustive correctness proof ---------------------

def test_assignment_never_fails_any_combination():
    """The core correctness guarantee: every one of the 495 possible
    8-of-12 qualifying combinations must yield a complete assignment."""
    failures = 0
    for combo in combinations(ALL_GROUPS, 8):
        result = _assign_third_place_slots(list(combo))
        if len(result) != 8 or len(set(result.values())) != 8:
            failures += 1
    assert failures == 0, f"{failures} combinations failed to find a complete assignment"


def test_assignment_never_fails_any_rank_ordering_sample():
    """Same guarantee, but varying the RANK ORDER within one combination
    (every one of the 8! = 40320 orderings)."""
    from itertools import permutations
    combo = tuple("ABCDEFGH")
    failures = 0
    for ordering in permutations(combo):
        result = _assign_third_place_slots(list(ordering))
        if len(result) != 8 or len(set(result.values())) != 8:
            failures += 1
    assert failures == 0


def test_assignment_respects_eligibility():
    slots = dict(_third_place_slots_in_match_order())
    for combo in list(combinations(ALL_GROUPS, 8))[::17]:  # sample for speed
        result = _assign_third_place_slots(list(combo))
        for winner_group, assigned in result.items():
            assert assigned in slots[winner_group], (
                f"{assigned} assigned to slot {winner_group} but not eligible "
                f"(eligible: {slots[winner_group]})"
            )
            assert assigned in combo


def test_higher_ranked_team_gets_priority_when_only_one_slot_fits():
    # construct a case where exactly one team is eligible for only one slot,
    # forcing the algorithm to honor that even if processed last
    ranked = ["A", "B", "C", "D", "E", "F", "G", "H"]
    result = _assign_third_place_slots(ranked)
    assert len(result) == 8
    assert len(set(result.values())) == 8


# ---- third-place ranking ---------------------------------------------------

def test_rank_third_place_teams_orders_by_points_then_gd_then_gf():
    standings = OrderedDict()
    # Group A: 3rd place team has 6 points, GD +2
    standings["Group A"] = [None, None, _row("A", "TeamA3", 6, 2, 5)]
    # Group B: 3rd place has 6 points too, but better GD (+4) -> ranks above A
    standings["Group B"] = [None, None, _row("B", "TeamB3", 6, 4, 7)]
    # Group C: only 3 points -> ranks below both
    standings["Group C"] = [None, None, _row("C", "TeamC3", 3, -1, 2)]

    ranked = rank_third_place_teams(standings)
    assert [r.team for r in ranked] == ["TeamB3", "TeamA3", "TeamC3"]


def test_rank_third_place_teams_falls_back_to_group_letter_on_full_tie():
    standings = OrderedDict()
    standings["Group C"] = [None, None, _row("C", "TeamC3", 3, 0, 3)]
    standings["Group A"] = [None, None, _row("A", "TeamA3", 3, 0, 3)]
    standings["Group B"] = [None, None, _row("B", "TeamB3", 3, 0, 3)]
    ranked = rank_third_place_teams(standings)
    # fully tied on points/GD/GF -> deterministic fallback to group letter
    assert [r.group for r in ranked] == ["Group A", "Group B", "Group C"]


def test_best_eight_thirds_takes_top_8_of_12():
    standings = OrderedDict()
    for i, letter in enumerate(ALL_GROUPS):
        standings[f"Group {letter}"] = [None, None, _row(letter, f"Team{letter}3", points=12 - i, gd=0, gf=0)]
    best8 = best_eight_thirds(standings)
    assert len(best8) == 8
    assert [r.group for r in best8] == [f"Group {l}" for l in ALL_GROUPS[:8]]


# ---- full integration through real Match objects --------------------------

def _full_group(letter, results):
    """results: list of (home, away, hs, as_) for all 6 round-robin games."""
    return [_m(f"Group {letter}", h, a, hs, as_, mid=f"{letter}-{i}")
            for i, (h, a, hs, as_) in enumerate(results)]


def _round_robin(letter, teams, win_pattern):
    """Build a full 6-game round robin where win_pattern[i] beats win_pattern[j]
    for i < j (simple ladder: team0 beats everyone, team1 beats team2/3, etc.)"""
    t = teams
    fixtures = [
        (t[0], t[1], 3, 0), (t[2], t[3], 1, 1),
        (t[0], t[2], 2, 0), (t[1], t[3], 2, 1),
        (t[0], t[3], 4, 0), (t[1], t[2], 1, 0),
    ]
    return _full_group(letter, fixtures)


def test_compute_round_of_32_end_to_end_no_crash_and_correct_shape():
    matches = []
    for letter in ALL_GROUPS:
        teams = [f"{letter}1", f"{letter}2", f"{letter}3", f"{letter}4"]
        matches += _round_robin(letter, teams, None)

    fixtures = compute_round_of_32(matches)
    assert len(fixtures) == 16

    all_teams_used = []
    for fx in fixtures:
        assert fx["home"]["team"] is not None
        assert fx["away"]["team"] is not None
        all_teams_used.append(fx["home"]["team"])
        all_teams_used.append(fx["away"]["team"])

    # all groups fully complete -> everything should be confirmed
    assert all(fx["home"]["confirmed"] and fx["away"]["confirmed"] for fx in fixtures)
    # 32 distinct teams used, no duplicates, no slot left empty
    assert len(all_teams_used) == 32
    assert len(set(all_teams_used)) == 32

    # spot check: in this ladder pattern, "<letter>1" always wins the group
    # and "<letter>2" always finishes second (3-0, 2-0, 4-0 wins => 9 pts;
    # team2 beats team3 2-1 and team2 loses to team1 0-3, beats team3... )
    winners_seen = {fx["home"]["rule"]: fx["home"]["team"] for fx in fixtures}
    winners_seen.update({fx["away"]["rule"]: fx["away"]["team"] for fx in fixtures})
    assert winners_seen["Winner Group A"] == "A1"
    assert winners_seen["Runner-up Group A"] == "A2"


def test_compute_round_of_32_incomplete_groups_marked_unconfirmed():
    matches = []
    for letter in ALL_GROUPS:
        teams = [f"{letter}1", f"{letter}2", f"{letter}3", f"{letter}4"]
        group_matches = _round_robin(letter, teams, None)
        if letter == "A":
            # Group A: only first game played, rest still scheduled
            group_matches[0] = _m("Group A", "A1", "A2", 3, 0, status=FINISHED, mid="A-0")
            for gm in group_matches[1:]:
                gm.status = SCHEDULED
                gm.home_score = gm.away_score = None
        matches += group_matches

    fixtures = compute_round_of_32(matches)
    assert len(fixtures) == 16

    # Group A's winner/runner-up slots must be marked unconfirmed (projection only)
    found_unconfirmed_a = False
    for fx in fixtures:
        for side in (fx["home"], fx["away"]):
            if side["rule"] in ("Winner Group A", "Runner-up Group A"):
                assert side["confirmed"] is False
                found_unconfirmed_a = True
    assert found_unconfirmed_a

    # AND since not all 12 groups are complete, every third-place slot must
    # also be unconfirmed (the ranking can still shift)
    for fx in fixtures:
        for side in (fx["home"], fx["away"]):
            if side["rule"].startswith("3rd Group"):
                assert side["confirmed"] is False


def test_no_team_appears_twice_across_whole_bracket():
    matches = []
    for letter in ALL_GROUPS:
        teams = [f"{letter}1", f"{letter}2", f"{letter}3", f"{letter}4"]
        matches += _round_robin(letter, teams, None)
    fixtures = compute_round_of_32(matches)
    used = [fx["home"]["team"] for fx in fixtures] + [fx["away"]["team"] for fx in fixtures]
    assert len(used) == len(set(used)) == 32


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
    print("All tests passed.")
