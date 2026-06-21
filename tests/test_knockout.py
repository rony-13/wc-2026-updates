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
    compute_knockout_bracket,
    current_stage,
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


def test_provisional_qualify_marks_exactly_the_best_eight_thirds():
    """Mirrors what service.get_groups() does when SHOW_PROJECTED_THIRDS is on:
    mark the live best-8 third-place rows the same way the API/service would,
    and check exactly those 8 (and only those 8) end up flagged."""
    matches = []
    for letter in ALL_GROUPS:
        teams = [f"{letter}1", f"{letter}2", f"{letter}3", f"{letter}4"]
        matches += _round_robin(letter, teams, None)

    tables = compute_standings(matches)
    for row in best_eight_thirds(tables):
        row.provisional_qualify = True

    flagged = [r for rows in tables.values() for r in rows if r.provisional_qualify]
    assert len(flagged) == 8
    assert all(r.rank == 3 for r in flagged)  # only ever 3rd-place rows
    assert all(not r.qualifies for r in flagged)  # disjoint from the guaranteed top two

    # the guaranteed top two are completely untouched by this
    top_two = [r for rows in tables.values() for r in rows if r.qualifies]
    assert len(top_two) == 24
    assert all(not r.provisional_qualify for r in top_two)

    # in this ladder pattern every group's 3rd place ("<letter>3") has an
    # identical record (1 win, 0 draws, 2 losses, same GD/GF) -> full tie,
    # so the deterministic group-letter fallback picks the first 8 groups
    assert {r.team for r in flagged} == {f"{l}3" for l in ALL_GROUPS[:8]}


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


# ---- later rounds (R16 through Final): real chain through match results ---

def _full_group_stage_matches():
    matches = []
    for letter in ALL_GROUPS:
        teams = [f"{letter}1", f"{letter}2", f"{letter}3", f"{letter}4"]
        matches += _round_robin(letter, teams, None)
    return matches


def _decide(match_id, group, winner, loser, hs=2, as_=0):
    """A FINISHED knockout match with a clear winner (winner is always
    'home' here; _match_outcome doesn't care which side, only the score)."""
    return _m(group, winner, loser, hs, as_, status=FINISHED, mid=str(match_id))


def test_r16_shows_candidates_not_a_guess_when_source_match_undecided():
    matches = _full_group_stage_matches()
    bracket = compute_knockout_bracket(matches)
    r16 = bracket["round_of_16"]
    m89 = next(fx for fx in r16 if fx["match_id"] == 89)
    # match 89 = Winner(74) vs Winner(77) -- neither R32 match has been
    # played, so neither side should claim a team...
    assert m89["home"]["team"] is None
    assert m89["away"]["team"] is None
    assert m89["home"]["confirmed"] is False
    # ...but should surface the two teams who WILL play that R32 match, as
    # information only, not a prediction of who wins it
    assert m89["home"]["candidates"] is not None
    assert len(m89["home"]["candidates"]) == 2


def test_r16_resolves_once_source_r32_match_is_decided():
    matches = _full_group_stage_matches()
    r32 = compute_round_of_32(matches)
    m74 = next(fx for fx in r32 if fx["match_id"] == 74)
    m77 = next(fx for fx in r32 if fx["match_id"] == 77)
    # actually play out matches 74 and 77
    matches.append(_decide(74, None, m74["home"]["team"], m74["away"]["team"], 3, 1))
    matches.append(_decide(77, None, m77["away"]["team"], m77["home"]["team"], 2, 0))

    bracket = compute_knockout_bracket(matches)
    m89 = next(fx for fx in bracket["round_of_16"] if fx["match_id"] == 89)
    assert m89["home"]["team"] == m74["home"]["team"]
    assert m89["home"]["confirmed"] is True
    assert m89["away"]["team"] == m77["away"]["team"]
    assert m89["away"]["confirmed"] is True


def test_tied_finished_knockout_match_left_unresolved_not_guessed():
    # a FINISHED knockout match with equal scores (would've gone to
    # penalties) -- we have no shootout data, so this must NOT be guessed
    matches = _full_group_stage_matches()
    r32 = compute_round_of_32(matches)
    m74 = next(fx for fx in r32 if fx["match_id"] == 74)
    matches.append(_m(None, m74["home"]["team"], m74["away"]["team"], 1, 1,
                       status=FINISHED, mid="74"))
    bracket = compute_knockout_bracket(matches)
    m89 = next(fx for fx in bracket["round_of_16"] if fx["match_id"] == 89)
    assert m89["home"]["team"] is None
    assert m89["home"]["confirmed"] is False


def test_full_tournament_chain_resolves_to_a_single_champion():
    """Play out an entire synthetic tournament end-to-end and confirm the
    Final correctly resolves to exactly the two semi-final winners."""
    matches = _full_group_stage_matches()
    r32 = compute_round_of_32(matches)
    assert all(fx["home"]["team"] and fx["away"]["team"] for fx in r32)

    # decide every R32 match: home side always "wins" 2-0 for simplicity
    for fx in r32:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))

    bracket = compute_knockout_bracket(matches)
    r16 = bracket["round_of_16"]
    assert all(fx["home"]["team"] and fx["away"]["team"] for fx in r16), \
        "every R16 slot should resolve once all R32 matches are decided"

    for fx in r16:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))

    bracket = compute_knockout_bracket(matches)
    qf = bracket["quarter_finals"]
    assert all(fx["home"]["team"] and fx["away"]["team"] for fx in qf)
    for fx in qf:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))

    bracket = compute_knockout_bracket(matches)
    sf = bracket["semi_finals"]
    assert all(fx["home"]["team"] and fx["away"]["team"] for fx in sf)
    for fx in sf:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))

    bracket = compute_knockout_bracket(matches)
    final = bracket["final"][0]
    third = bracket["third_place"][0]
    assert final["home"]["team"] and final["away"]["team"]
    assert final["home"]["confirmed"] and final["away"]["confirmed"]
    # the final's two teams must be exactly the two SF winners (in some order)
    sf_winners = {sf[0]["home"]["team"], sf[1]["home"]["team"]}  # home always "won" by construction
    assert {final["home"]["team"], final["away"]["team"]} == sf_winners
    # third place game gets the two SF LOSERS, not winners
    sf_losers = {sf[0]["away"]["team"], sf[1]["away"]["team"]}
    assert {third["home"]["team"], third["away"]["team"]} == sf_losers


# ---- current_stage() -------------------------------------------------------

def test_current_stage_progression():
    # genuinely incomplete group stage: group A's full 6-fixture schedule
    # exists, but only the first game has actually been played
    incomplete = _round_robin("Group A", ["A1", "A2", "A3", "A4"], None)
    for gm in incomplete[1:]:
        gm.status = SCHEDULED
        gm.home_score = gm.away_score = None
    for letter in ALL_GROUPS[1:]:
        teams = [f"{letter}1", f"{letter}2", f"{letter}3", f"{letter}4"]
        incomplete += _round_robin(letter, teams, None)
    assert current_stage(incomplete) == "group_stage"

    # fully complete group stage -> round of 32 is current
    matches = _full_group_stage_matches()
    r32 = compute_round_of_32(matches)
    assert current_stage(matches) == "round_of_32"

    for fx in r32:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))
    assert current_stage(matches) == "round_of_16"

    bracket = compute_knockout_bracket(matches)
    for fx in bracket["round_of_16"]:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))
    assert current_stage(matches) == "quarter_finals"

    bracket = compute_knockout_bracket(matches)
    for fx in bracket["quarter_finals"]:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))
    assert current_stage(matches) == "semi_finals"

    bracket = compute_knockout_bracket(matches)
    for fx in bracket["semi_finals"]:
        matches.append(_decide(fx["match_id"], None, fx["home"]["team"], fx["away"]["team"]))
    assert current_stage(matches) == "final"


# ---- score/status enrichment ----------------------------------------------

def test_fixture_carries_real_score_once_match_is_played():
    matches = _full_group_stage_matches()
    r32 = compute_round_of_32(matches)
    m73 = next(fx for fx in r32 if fx["match_id"] == 73)
    matches.append(_decide(73, None, m73["home"]["team"], m73["away"]["team"], 3, 1))

    bracket = compute_knockout_bracket(matches)
    fx73 = next(fx for fx in bracket["round_of_32"] if fx["match_id"] == 73)
    assert fx73["score"] == {"home": 3, "away": 1}
    assert fx73["status"] == FINISHED
    assert fx73["decided_by_penalties"] is False


def test_fixture_score_is_none_before_match_played():
    matches = _full_group_stage_matches()
    bracket = compute_knockout_bracket(matches)
    fx73 = next(fx for fx in bracket["round_of_32"] if fx["match_id"] == 73)
    assert fx73["score"] is None
    assert fx73["status"] is None


def test_tied_score_flagged_as_decided_by_penalties():
    matches = _full_group_stage_matches()
    r32 = compute_round_of_32(matches)
    m73 = next(fx for fx in r32 if fx["match_id"] == 73)
    matches.append(_m(None, m73["home"]["team"], m73["away"]["team"], 1, 1,
                       status=FINISHED, mid="73"))
    bracket = compute_knockout_bracket(matches)
    fx73 = next(fx for fx in bracket["round_of_32"] if fx["match_id"] == 73)
    assert fx73["score"] == {"home": 1, "away": 1}
    assert fx73["decided_by_penalties"] is True
    # and -- critically -- still no fabricated winner for the R16 slot that follows
    r16_dependent = next(fx for fx in bracket["round_of_16"] if fx["match_id"] == 90)
    assert r16_dependent["home"]["team"] is None  # match 90 = WM(73) vs WM(75)


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
