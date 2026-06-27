"""Best-third-place ranking and Round-of-32 bracket projection.

Of the 12 group winners and 12 runners-up, all 24 advance automatically.
The remaining 8 of the 32 Round-of-32 slots go to the best 8 of the 12
third-placed teams, ranked per FIFA's published tiebreaker order
(https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers,
confirmed against ESPN's explainer of the same rules):

    1. Points
    2. Goal difference (all group matches)
    3. Goals scored (all group matches)
    4. Team conduct score (yellow/red cards: yellow -1, indirect red -3,
       direct red -4, yellow+direct red -5)
    5. FIFA world ranking

Criteria 4 and 5 are NOT implemented: neither live data source
(worldcup26.ir nor openfootball) exposes card/disciplinary data at all, and
we don't have a bundled FIFA world ranking snapshot. In practice this
tiebreaker is rarely reached -- points/GD/GF usually separate teams -- but
when it is, ties fall back to group letter for a stable, repeatable order
rather than crashing or being run-order-dependent. This is a known,
intentional limitation; revisit if a ranking data source becomes available.

THE ROUND-OF-32 BRACKET TEMPLATE (R32_TEMPLATE below) was extracted
directly from a real worldcup26.ir API payload (all 16 Round-of-32
fixtures' home_team_label/away_team_label fields), not guessed or scraped
from prose -- it's the tournament's own real schedule data. 8 of the 16
fixtures pair specific groups' winners/runners-up directly with no
third-place involvement; the other 8 pair a group's winner against "the
best-placed qualifying third from one of these 5 specific groups."

ASSIGNING qualifying third-place teams to those 8 slots is NOT something we
compute or match-make ourselves: FIFA publishes the exact slotting as a
fixed lookup table (Annexe C of the FIFA World Cup 2026 Regulations), one
row for each of the 495 possible 8-of-12 qualifying combinations. The
assignment depends ONLY on WHICH 8 groups supply a qualifying third -- not
on the teams' rank order among the 8, and not on any draw. So given the set
of 8 qualifying groups we look the slotting up directly in
data/annex_c_allocation.json (see _assign_third_place_slots).

  Earlier versions of this module instead ran a bipartite matching
  (Kuhn's algorithm) to fill the slots. That was a real bug: a matching
  finds *a* valid assignment, but many combinations admit several valid
  matchings, and FIFA's published one is a specific choice the algorithm
  had no way to reproduce. The result was a bracket that satisfied every
  eligibility rule yet still disagreed with FIFA / Google / Olympics
  (e.g. it paired Germany-vs-3rd-of-A and France-vs-3rd-of-D when the
  official slotting is Germany-vs-3rd-of-D (Paraguay) and France-vs-3rd-
  of-F (Sweden)). The Annexe C lookup replaces that guess with the real
  table.

data/annex_c_allocation.json reproduces FIFA's Annexe C exactly (all 3,960
group-to-slot entries cross-checked against the official FIFA regulations
PDF; eligibility, bijection and no-team-faces-its-own-group-winner
invariants all verified in tests). The instant a Round-of-32 fixture's real
team names appear in the live feed (replacing the placeholder labels),
that's FIFA's actual official assignment and should still be preferred over
this projection -- see service.py's merge logic -- but the projection now
matches it rather than diverging from it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from collections import OrderedDict

from .models import Match, FINISHED
from .standings import compute_standings

# FIFA's official Annexe C third-place allocation table: 495 rows, one per
# possible 8-of-12 qualifying combination. Key = the 8 qualifying groups'
# letters sorted into a string (e.g. "ABCDEFGH"); value = {"1A": "<group>",
# ...} mapping each group-winner slot to the third-placed group it faces.
_ALLOCATION_PATH = Path(__file__).with_name("data") / "annex_c_allocation.json"
with _ALLOCATION_PATH.open(encoding="utf-8") as _f:
    ANNEX_C_ALLOCATION: Dict[str, Dict[str, str]] = json.load(_f)

# (match_id, (home_role, home_arg), (away_role, away_arg))
#   role "W"   -> winner of group `arg` (a single letter)
#   role "RU"  -> runner-up of group `arg` (a single letter)
#   role "3RD" -> best qualifying third-place team from one of the groups in
#                 `arg` (a frozenset of letters), resolved via ranking
R32_TEMPLATE = [
    (73, ("RU", "A"), ("RU", "B")),
    (74, ("W", "E"), ("3RD", frozenset("ABCDF"))),
    (75, ("W", "F"), ("RU", "C")),
    (76, ("W", "C"), ("RU", "F")),
    (77, ("W", "I"), ("3RD", frozenset("CDFGH"))),
    (78, ("RU", "E"), ("RU", "I")),
    (79, ("W", "A"), ("3RD", frozenset("CEFHI"))),
    (80, ("W", "L"), ("3RD", frozenset("EHIJK"))),
    (81, ("W", "D"), ("3RD", frozenset("BEFIJ"))),
    (82, ("W", "G"), ("3RD", frozenset("AEHIJ"))),
    (83, ("RU", "K"), ("RU", "L")),
    (84, ("W", "H"), ("RU", "J")),
    (85, ("W", "B"), ("3RD", frozenset("EFGIJ"))),
    (86, ("W", "J"), ("RU", "H")),
    (87, ("W", "K"), ("3RD", frozenset("DEIJL"))),
    (88, ("RU", "D"), ("RU", "G")),
]


def _group_letter(group_name: str) -> str:
    """'Group A' -> 'A'"""
    return group_name.replace("Group ", "").strip()


def _group_complete(matches: List[Match], group_name: str) -> bool:
    group_matches = [m for m in matches if m.group == group_name]
    return bool(group_matches) and all(m.status == FINISHED for m in group_matches)


def rank_third_place_teams(standings) -> list:
    """All 12 third-placed teams (one per group), ranked best-to-worst by
    FIFA's points -> goal difference -> goals-scored order. See module
    docstring for the documented gap on criteria 4-5."""
    thirds = [rows[2] for rows in standings.values() if len(rows) >= 3]
    return sorted(
        thirds,
        key=lambda r: (-r.points, -r.goal_difference, -r.goals_for, r.group),
    )


def best_eight_thirds(standings) -> list:
    return rank_third_place_teams(standings)[:8]


def _third_place_slots_in_match_order() -> List[tuple]:
    """(winner_group_letter, eligible_groups_frozenset) for the 8 slots
    that pair a group's winner against a best-qualifying-third, in
    ascending match-id order (R32_TEMPLATE is already sorted that way)."""
    slots = []
    for match_id, (h_role, h_arg), (a_role, a_arg) in R32_TEMPLATE:
        if h_role == "3RD":
            slots.append((a_arg, h_arg))      # away side holds the winner-group here
        elif a_role == "3RD":
            slots.append((h_arg, a_arg))      # home side holds the winner-group here
    return slots


def _assign_third_place_slots(qualifying_group_letters: List[str]) -> Dict[str, str]:
    """Map each group-winner slot to the third-placed group it faces, using
    FIFA's official Annexe C allocation table.

    `qualifying_group_letters` is the set of groups whose third-placed teams
    qualify (the best 8). Annexe C keys ONLY on this set -- the rank order
    among the 8 is irrelevant to the slotting -- so the input order does not
    matter. Returns {winner_group_letter: third_place_group_letter}, e.g.
    {"E": "D", "I": "F", ...}.

    Returns {} when a complete set of exactly 8 distinct qualifying groups
    isn't known yet (early in the tournament, before enough groups have a
    third-placed team). In that case the 3RD slots simply stay unresolved
    rather than showing a guess -- the assignment genuinely cannot be known
    until the 8 qualifiers are settled.
    """
    groups = sorted(set(qualifying_group_letters))
    if len(groups) != 8:
        return {}
    row = ANNEX_C_ALLOCATION.get("".join(groups))
    if row is None:
        return {}
    # row keys are winner slots "1A".."1L"; strip the leading "1" to get the
    # bare winner-group letter the caller resolves against.
    return {slot[1:]: third_group for slot, third_group in row.items()}


def compute_round_of_32(matches: List[Match]) -> List[dict]:
    """Returns the 16 Round-of-32 fixtures with each side resolved to a
    team name where possible. Each side carries:
        rule       -- human-readable description ("Winner Group A", "3rd
                       Group C/E/F/H/I")
        team       -- resolved team name, or None if not yet determinable
        confirmed  -- True only once the source group's standings (for W/RU)
                      or ALL 12 groups (for 3RD, since the ranking can shift
                      from any group's remaining results) are final. False
                      means "current best guess, can still change."
    """
    standings = compute_standings(matches)
    group_complete = {
        _group_letter(g): _group_complete(matches, g) for g in standings
    }
    all_complete = len(standings) == 12 and all(group_complete.values())

    winners = {_group_letter(g): rows[0].team for g, rows in standings.items() if rows}
    runners_up = {_group_letter(g): rows[1].team for g, rows in standings.items() if len(rows) >= 2}

    best8 = best_eight_thirds(standings)
    best8_letters = [_group_letter(r.group) for r in best8]
    best8_team_by_letter = {_group_letter(r.group): r.team for r in best8}
    slot_assignment = _assign_third_place_slots(best8_letters)  # {winner_group: third_group}

    def resolve(role, arg, sibling_role, sibling_arg):
        if role == "W":
            return {
                "rule": f"Winner Group {arg}",
                "team": winners.get(arg),
                "confirmed": group_complete.get(arg, False),
            }
        if role == "RU":
            return {
                "rule": f"Runner-up Group {arg}",
                "team": runners_up.get(arg),
                "confirmed": group_complete.get(arg, False),
            }
        # role == "3RD" -- the sibling side is always this slot's "W" group
        label = "/".join(sorted(arg))
        third_group = slot_assignment.get(sibling_arg) if sibling_role == "W" else None
        team = best8_team_by_letter.get(third_group) if third_group else None
        return {
            "rule": f"3rd Group {label}",
            "team": team,
            "confirmed": all_complete,
        }

    fixtures = []
    for match_id, (h_role, h_arg), (a_role, a_arg) in R32_TEMPLATE:
        home = resolve(h_role, h_arg, a_role, a_arg)
        away = resolve(a_role, a_arg, h_role, h_arg)
        fixtures.append({"match_id": match_id, "home": home, "away": away})

    return fixtures


# ---------------------------------------------------------------------------
# Round of 16 through the Final.
#
# Unlike the Round of 32, none of this involves predicting who WINS a given
# match -- that's not something this app does or should claim to do. Each
# later-round slot just references an earlier match by id ("WM" = winner of
# that match, "LM" = loser of it, for the third-place game). The two
# templates below were extracted directly from the real worldcup26.ir
# schedule data (match ids 89-104), same as R32_TEMPLATE.
ROUND_OF_16_TEMPLATE = [
    (89, ("WM", 74), ("WM", 77)),
    (90, ("WM", 73), ("WM", 75)),
    (91, ("WM", 76), ("WM", 78)),
    (92, ("WM", 79), ("WM", 80)),
    (93, ("WM", 83), ("WM", 84)),
    (94, ("WM", 81), ("WM", 82)),
    (95, ("WM", 86), ("WM", 88)),
    (96, ("WM", 85), ("WM", 87)),
]
QUARTER_FINALS_TEMPLATE = [
    (97, ("WM", 89), ("WM", 90)),
    (98, ("WM", 93), ("WM", 94)),
    (99, ("WM", 91), ("WM", 92)),
    (100, ("WM", 95), ("WM", 96)),
]
SEMI_FINALS_TEMPLATE = [
    (101, ("WM", 97), ("WM", 98)),
    (102, ("WM", 99), ("WM", 100)),
]
THIRD_PLACE_TEMPLATE = [
    (103, ("LM", 101), ("LM", 102)),
]
FINAL_TEMPLATE = [
    (104, ("WM", 101), ("WM", 102)),
]


def _match_outcome(m: Optional[Match]):
    """Returns (winner, loser), or (None, None) if not yet determinable.
    A tied score on a FINISHED knockout match means it went to penalties --
    this feed has no shootout data, so that case is also left unresolved
    rather than guessed."""
    if m is None or m.status != FINISHED or m.home_score is None or m.away_score is None:
        return None, None
    if m.home_score > m.away_score:
        return m.home, m.away
    if m.away_score > m.home_score:
        return m.away, m.home
    return None, None  # draw at full time -- decided by penalties, not in this feed


def _attach_match_result(fixture: dict, by_id: Dict[str, Match]) -> dict:
    """Overlay the REAL match record's score/status/kickoff onto a computed
    fixture, independent of how its home/away got resolved (group
    projection for R32, or an earlier-round chain for R16+). A tied score
    on a FINISHED match is exposed via `decided_by_penalties` -- the score
    itself is real and worth showing, even though (per _match_outcome) we
    can't say who actually won without shootout data this feed lacks."""
    m = by_id.get(str(fixture["match_id"]))
    fixture["status"] = m.status if m else None
    fixture["kickoff"] = m.utc_date if m else None
    fixture["venue"] = m.venue if m else None
    if m and m.home_score is not None and m.away_score is not None:
        fixture["score"] = {"home": m.home_score, "away": m.away_score}
        fixture["decided_by_penalties"] = (
            m.status == FINISHED and m.home_score == m.away_score
        )
    else:
        fixture["score"] = None
        fixture["decided_by_penalties"] = False
    return fixture


def _resolve_chain_round(
    template: list, by_id: Dict[str, Match], by_id_resolved: Dict[int, dict],
) -> List[dict]:
    """Resolve one later-round (R16+) using already-resolved earlier rounds.
    `by_id_resolved` accumulates {match_id: fixture_dict} across rounds as
    they're computed, in order, so each round can look up its own sources."""
    fixtures = []

    def resolve(role: str, ref_match_id: int) -> dict:
        ref_real = by_id.get(str(ref_match_id))
        winner, loser = _match_outcome(ref_real)
        team = winner if role == "WM" else loser
        verb = "Winner" if role == "WM" else "Loser"
        result = {
            "rule": f"{verb} of Match {ref_match_id}",
            "team": team,
            "confirmed": team is not None,
            "candidates": None,
        }
        if team is None:
            # not decided yet -- surface the two teams competing in the
            # source match, if known, purely as information (not a guess at
            # who wins)
            ref_fixture = by_id_resolved.get(ref_match_id)
            if ref_fixture:
                c = [ref_fixture["home"]["team"], ref_fixture["away"]["team"]]
                result["candidates"] = [t for t in c if t] or None
        return result

    for match_id, (h_role, h_arg), (a_role, a_arg) in template:
        home = resolve(h_role, h_arg)
        away = resolve(a_role, a_arg)
        fx = {"match_id": match_id, "home": home, "away": away}
        _attach_match_result(fx, by_id)
        fixtures.append(fx)
        by_id_resolved[match_id] = fx
    return fixtures


def compute_knockout_bracket(matches: List[Match]) -> Dict[str, list]:
    """Full bracket, all rounds, dynamically resolved from current match
    data. Round of 32 is a live projection from group standings (see
    compute_round_of_32); every later round only ever shows a team once
    its actual source match has been played and decided -- never a
    speculative guess at who wins. Every fixture (all rounds) also carries
    the real match's own score/status/kickoff once that specific match
    exists in current data, regardless of how its participants resolved."""
    by_id: Dict[str, Match] = {m.id: m for m in matches}
    by_id_resolved: Dict[int, dict] = {}

    r32 = compute_round_of_32(matches)
    for fx in r32:
        _attach_match_result(fx, by_id)
        by_id_resolved[fx["match_id"]] = fx

    r16 = _resolve_chain_round(ROUND_OF_16_TEMPLATE, by_id, by_id_resolved)
    qf = _resolve_chain_round(QUARTER_FINALS_TEMPLATE, by_id, by_id_resolved)
    sf = _resolve_chain_round(SEMI_FINALS_TEMPLATE, by_id, by_id_resolved)
    third = _resolve_chain_round(THIRD_PLACE_TEMPLATE, by_id, by_id_resolved)
    final = _resolve_chain_round(FINAL_TEMPLATE, by_id, by_id_resolved)

    return {
        "round_of_32": r32,
        "round_of_16": r16,
        "quarter_finals": qf,
        "semi_finals": sf,
        "third_place": third,
        "final": final,
    }


def current_stage(matches: List[Match]) -> str:
    """Which stage should be the default tab right now: the earliest stage
    that isn't fully decided yet. Falls through group stage -> R32 -> R16 ->
    QF -> SF -> final once everything before it is finished."""
    standings = compute_standings(matches)
    groups_done = len(standings) == 12 and all(
        _group_complete(matches, g) for g in standings
    )
    if not groups_done:
        return "group_stage"

    by_id: Dict[str, Match] = {m.id: m for m in matches}

    def round_done(template: list) -> bool:
        for match_id, _, _ in template:
            m = by_id.get(str(match_id))
            if m is None or m.status != FINISHED:
                return False
        return True

    if not round_done(R32_TEMPLATE):
        return "round_of_32"
    if not round_done(ROUND_OF_16_TEMPLATE):
        return "round_of_16"
    if not round_done(QUARTER_FINALS_TEMPLATE):
        return "quarter_finals"
    if not round_done(SEMI_FINALS_TEMPLATE):
        return "semi_finals"
    return "final"
