import pytest

from services.ai_recap import RECAP_EXAMPLES, recap_facts
from services.recap_story import (build_facts_packet, numbers_in, pick_story_angles, player_round_stats,
                                  validate_recap)

FEMBOY = {"puuid": "p1", "name": "femboy", "team_id": "Red", "agent": {"name": "Jett"},
          "stats": {"kills": 18, "deaths": 16, "assists": 2, "score": 205 * 18}}
RIA = {"puuid": "p2", "name": "ria", "team_id": "Red", "agent": {"name": "Sage"},
       "stats": {"kills": 7, "deaths": 17, "assists": 5, "score": 115 * 18}}
RANDOS = [{"puuid": f"r{i}", "name": f"Rando{i}", "team_id": "Red"} for i in range(3)]
ENEMIES = [{"puuid": f"e{i}", "name": f"Enemy{i}", "team_id": "Blue"} for i in range(5)]


def _kill(round_index, ms, killer, victim, weapon="Vandal"):
    return {"round": round_index, "time_in_round_in_ms": ms, "killer": {"puuid": killer["puuid"]},
            "victim": {"puuid": victim["puuid"]}, "weapon": {"name": weapon, "type": "Weapon"}}


def haven_collapse():
    """5-13 on Haven: femboy aces round 1, loses a 1v5 in round 2, ria 3Ks round 12, 0-6 second half."""
    winners = ["Red"] * 5 + ["Blue"] * 7 + ["Blue"] * 6
    winners[1], winners[5] = "Blue", "Red"  # round 2 is the lost clutch; keep the first half at 5-7
    kills = [_kill(0, 1000 * (i + 1), FEMBOY, enemy, "Sheriff") for i, enemy in enumerate(ENEMIES)]
    kills += [_kill(1, 1000 * (i + 1), ENEMIES[0], victim) for i, victim in enumerate([*RANDOS, RIA])]
    kills += [_kill(1, 6000, FEMBOY, ENEMIES[0]), _kill(1, 7000, ENEMIES[1], FEMBOY)]
    kills += [_kill(11, 1000 * (i + 1), RIA, enemy, "Odin") for i, enemy in enumerate(ENEMIES[:3])]
    return {
        "players": [FEMBOY, RIA, *RANDOS, *ENEMIES],
        "metadata": {"map": {"name": "Haven"}},
        "teams": [{"team_id": "Red", "won": False, "rounds": {"won": 5, "lost": 13}}, {"team_id": "Blue"}],
        "rounds": [{"id": index, "winning_team": winner} for index, winner in enumerate(winners)],
        "kills": kills,
    }


def packet_for(detail, recap_context=None, squad_context=None):
    squad = [FEMBOY, RIA]
    facts = recap_facts(detail, squad, FEMBOY, registered_only=True)
    return build_facts_packet(detail, squad, FEMBOY, facts, recap_context, squad_context)


def test_round_stats_count_first_bloods_weapons_and_clutches():
    stats = player_round_stats(haven_collapse(), [FEMBOY, RIA], "Red")
    assert stats["p1"]["first_bloods"] == 1
    assert stats["p1"]["weapons"]["Sheriff"] == 5
    assert stats["p1"]["clutches"] == [0, 1]
    assert stats["p2"]["clutches"] == [0, 0]
    assert stats["p2"]["round_kills"][12] == 3


def test_clutches_are_skipped_without_full_rosters():
    detail = haven_collapse()
    detail["players"] = [FEMBOY, RIA, *ENEMIES]
    assert player_round_stats(detail, [FEMBOY, RIA], "Red")["p1"]["clutches"] == [0, 0]


def test_facts_packet_precomputes_every_number():
    packet, players = packet_for(haven_collapse(), squad_context={"games_together": 62})
    lines = packet.splitlines()
    assert lines[0] == "RESULT: Defeat 5-13 on Haven"
    assert lines[1] == ("STORY_ANGLE: femboy aced round 1 with the Sheriff, "
                        "then went 0.81 KD for the rest of the match")
    assert lines[2] == "SECOND_ANGLE: the team won 0 rounds in the second half (0-6)"
    assert "HALVES: first half 5-7, second half 0-6" in lines
    femboy = next(line for line in lines if line.startswith("- femboy (Jett):"))
    assert "18/16/2 (1.12 KD)" in femboy and "205 ACS" in femboy and "clutches" not in femboy
    assert "after round 1: 13/16 (0.81 KD)" in femboy and "best weapon Sheriff (6 kills)" not in femboy
    ria = next(line for line in lines if line.startswith("- ria (Sage):"))
    assert "7/17/5 (0.41 KD)" in ria and "115 ACS" in ria and "best weapon Odin (3 kills)" in ria
    assert "- femboy ace in round 1 (Sheriff)" in lines and "- ria 3K in round 12 (Odin)" in lines
    assert "TOGETHER: 62 games" in lines and "SQUAD_AVG_ACS" not in packet
    assert "Rando0" not in packet and "Enemy0" not in packet
    assert players["femboy"]["after_big_round"]["kd"] == "0.81"


def test_rank_up_then_loss_outranks_every_other_angle():
    context = [{"player": "ria", "rank_changes": [
        {"when": "yesterday", "direction": "up", "from_rank": "Platinum 3", "to_rank": "Diamond 1"}]}]
    packet, _ = packet_for(haven_collapse(), recap_context=context)
    assert "STORY_ANGLE: ria ranked up to Diamond 1 yesterday, then went 7/17/5 (0.41 KD) in this loss" in packet
    assert "SECOND_ANGLE: femboy aced round 1" in packet
    assert "RANK: ria ranked up from Platinum 3 to Diamond 1 yesterday" in packet


@pytest.mark.parametrize("halves,score,expected", [
    ({"first_half": [8, 4], "second_half": [2, 9]}, (10, 13), "the team led 8-4 at halftime and still lost 10-13"),
    ({"first_half": [4, 8], "second_half": [9, 3]}, (13, 11), "the team trailed 4-8 at halftime and came back"),
])
def test_half_split_angles(halves, score, expected):
    facts = {"rounds": {"won": score[0], "lost": score[1]}, "half_results": halves}
    assert pick_story_angles(facts, {})[0].startswith(expected)


def test_quiet_game_falls_back_to_top_acs_angle():
    facts = {"rounds": {"won": 13, "lost": 9}}
    players = {"One": {"acs": 240, "kd": "1.10"}, "Two": {"acs": 190, "kd": "0.95"}}
    assert pick_story_angles(facts, players) == ["One led the squad with 240 ACS in a 13-9 win"]


def test_smurf_and_lore_angles_are_available():
    facts = {"rounds": {"won": 4, "lost": 13}}
    players = {"Alt": {"is_smurf": True, "poor_smurf_performance": True, "kd": "0.50", "deaths": 12,
                       "kda_text": "6/12/2 (0.50 KD)"}}
    lore = {"callback": {"label": "Clutch Allergy", "kind": "inside joke", "player": "Alt",
                         "match_evidence": "The team recorded a loss."}}
    angles = pick_story_angles(facts, players, squad_context=lore)
    assert angles == ["Alt was on a smurf account and still went 6/12/2 (0.50 KD)",
                      'squad lore "Clutch Allergy" applies: The team recorded a loss']


# The examples are the brief's original wording, which uses a few numbers its facts packet can't back up
# ("24 HOURS", "the other 14 deaths", "game 41"). Pin exactly those so nothing else slips in.
@pytest.mark.parametrize("index,expected", [(0, ["numbers not in FACTS: 24"]),
                                            (1, ["numbers not in FACTS: 14, 41"])])
def test_few_shot_examples_only_go_beyond_their_facts_where_the_original_did(index, expected):
    packet, answer = RECAP_EXAMPLES[index]
    names = {"Kevin", "Spam", "ria"}
    assert validate_recap(answer, packet, names=names, labels={"Clutch Allergy"})[1] == expected


def test_numbers_include_spelled_out_values_from_three_up():
    assert numbers_in("Sixty-two games, three first bloods, two ranks below, one round") == {62.0, 3.0}
    assert numbers_in("Spam2 went 7/18/7 and 0.39 KD", exempt={"Spam2"}) == {7.0, 18.0, 0.39}


def test_validator_rejects_invented_numbers_and_strangers():
    packet = "RESULT: Defeat 5-13 on Haven\nPLAYERS:\n- Friend (Sage): 7/17/5 (0.41 KD), 115 ACS"
    padding = " Nothing else here carries a figure at all, which is exactly the point of this padding." * 7
    good = {"headline": "haven eats friend alive", "body": "@Friend went 7/17/5 in a 5-13 loss." + padding}
    recap, problems = validate_recap(good, packet, names={"Friend"})
    assert problems == []
    assert recap["headline"] == "HAVEN EATS FRIEND ALIVE" and recap["recap"].startswith("Friend went")

    invented = dict(good, body="Friend went 7/17/5 with 412 ADR and twenty kills." + padding)
    assert "numbers not in FACTS: 20, 412" in validate_recap(invented, packet, names={"Friend"})[1]
    formerly_banned = dict(good, body="Friend struggled to a 5-13 loss despite everything." + padding)
    assert validate_recap(formerly_banned, packet, names={"Friend"})[1] == []
    stranger = dict(good, body="Friend and Stranger lost 5-13." + padding)
    assert "mentioned players not in FEATURED or ALSO PLAYED" in validate_recap(stranger, packet, names={"Friend"},
                                                                 other_names={"Stranger"})[1]
    long_headline = dict(good, headline="ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE")
    assert any("headline" in p for p in validate_recap(long_headline, packet)[1])
    short = dict(good, body="Friend went 7/17/5.")
    assert any("words" in p for p in validate_recap(short, packet)[1])
    assert validate_recap("not json", packet)[0] is None


def test_body_allows_up_to_200_words():
    packet = "RESULT: Defeat 5-13 on Haven"
    def body(words):
        return " ".join(["Haven"] + ["word"] * (words - 1))
    assert validate_recap({"headline": "HAVEN", "body": body(200)}, packet)[1] == []
    problems = validate_recap({"headline": "HAVEN", "body": body(201)}, packet)[1]
    assert problems == ["the body had 201 words; it must be 70-200 words"]


def _summit_squad():
    """The five-stack from the 13-11 Summit card that read like a scoreboard."""
    rows = [("kitty meow meow", "Clove", 14, 17, 9, 162), ("Sugoicore", "Yoru", 29, 16, 4, 315),
            ("XxDeviousMoneyXx", "Harbor", 13, 18, 12, 160), ("AbnormalUNC", "Jett", 20, 15, 6, 245),
            ("Soupreme", "Chamber", 18, 14, 7, 212)]
    return [{"puuid": f"s{i}", "name": name, "team_id": "Red", "agent": {"name": agent},
             "is_smurf": name == "AbnormalUNC",
             "stats": {"kills": k, "deaths": d, "assists": a, "score": acs * 24}}
            for i, (name, agent, k, d, a, acs) in enumerate(rows)]


def test_five_stack_packet_features_only_the_story_players_and_drops_noise():
    squad = _summit_squad()
    winners = ["Red"] * 5 + ["Blue"] * 7 + ["Red"] * 8 + ["Blue"] * 4
    detail = {"players": squad, "metadata": {"map": {"name": "Summit"}},
              "teams": [{"team_id": "Red", "won": True, "rounds": {"won": 13, "lost": 11}}, {"team_id": "Blue"}],
              "rounds": [{"id": i, "winning_team": w} for i, w in enumerate(winners)], "kills": []}
    facts = recap_facts(detail, squad, squad[0], registered_only=True)
    packet, _ = build_facts_packet(detail, squad, squad[0], facts, squad_context={"games_together": 1})
    lines = packet.splitlines()
    assert lines[1].startswith("STORY_ANGLE: the team trailed 5-7 at halftime and came back to win 13-11")
    featured = [line for line in lines if line.startswith("- ")]
    assert [line.split(" (")[0] for line in featured] == ["- Sugoicore", "- XxDeviousMoneyXx"]
    assert "ALSO PLAYED: kitty meow meow (Clove), AbnormalUNC (Jett), Soupreme (Chamber)" in lines
    assert "TOGETHER" not in packet and "SQUAD_AVG_ACS" not in packet


def test_validator_rejects_a_player_by_player_rundown():
    names = {"One", "Two", "Three", "Four"}
    packet = "RESULT: Victory 13-11 on Summit"
    padding = " This padding has no figures and exists only to reach the minimum length for a body." * 6
    rundown = {"headline": "SUMMIT", "body": "One carried, Two helped, Three tried and Four existed." + padding}
    assert validate_recap(rundown, packet, names=names)[1] == [
        "named 4 players; tell one story about at most 3, not a player-by-player rundown"]
    story = dict(rundown, body="One carried while Two watched." + padding)
    assert validate_recap(story, packet, names=names)[1] == []
