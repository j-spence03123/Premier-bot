from io import BytesIO

from PIL import Image

from graphics.lineup import render_lineup_card
from graphics.help_card import render_help_card
from graphics.match_card import (ROUND_STRIP_HEIGHT, _assign_unique_tags, _build_tracked, _round_results,
                                 draw_play_result)
from graphics.player_history import rank_summary, render_player_history
from graphics.playbook_card import render_playbook_card, render_strategy_card
from graphics.rank_change import draw_rank_change_card
from graphics.schedule import render_schedule_card


def _png_size(buffer):
    with Image.open(BytesIO(buffer.getvalue())) as image:
        assert image.format == "PNG"
        return image.size


def test_tied_tags_go_to_eligible_player_with_fewer_awards():
    players = [
        {"tags": ["MVP", "ASSIST KING", "SURVIVOR"]},
        {"tags": ["ASSIST KING", "SURVIVOR"]},
        {"tags": ["LVP"]},
    ]

    _assign_unique_tags(players)

    assert players[0]["tags"] == ["MVP", "SURVIVOR"]
    assert players[1]["tags"] == ["ASSIST KING"]
    assert players[2]["tags"] == ["LVP"]


def test_ace_clutch_and_victim_tags_are_shared_between_players():
    players = [
        {"tags": ["ACE", "MVP", "CLUTCH x2", "VICTIM"]},
        {"tags": ["ACE", "MVP", "CLUTCH x1", "VICTIM"]},
    ]

    _assign_unique_tags(players)

    assert players[0]["tags"] == ["ACE", "MVP", "CLUTCH x2", "VICTIM"]
    assert players[1]["tags"] == ["ACE", "CLUTCH x1", "VICTIM"]


def _tag_player(index, team="Red", score=4000, kills=16, headshots=10, bodyshots=30, friendly_fire=0):
    return {
        "puuid": f"{team}-{index}", "name": f"{team} {index}", "tag": "EU", "team_id": team,
        "behavior": {"friendly_fire": {"incoming": 0, "outgoing": friendly_fire}},
        "stats": {"kills": kills, "deaths": 14, "assists": 3, "score": score,
                  "headshots": headshots, "bodyshots": bodyshots, "legshots": 0,
                  "damage": {"dealt": 2000}},
    }


def _kill(round_number, killer, victim, weapon="Vandal", time=10_000):
    return {"round": round_number, "time_in_round_in_ms": time,
            "killer": {"puuid": killer}, "victim": {"puuid": victim},
            "weapon": {"name": weapon, "type": "Weapon"}}


def _tags_for(players, enemies, kills=(), rounds=()):
    detail = {"players": players + enemies, "kills": list(kills), "rounds": list(rounds)}
    first_bloods, first_deaths, kills_per_round = {}, {}, {}
    by_round = {}
    for event in kills:
        by_round.setdefault(event["round"], []).append(event)
        counts = kills_per_round.setdefault(event["round"], {})
        counts[event["killer"]["puuid"]] = counts.get(event["killer"]["puuid"], 0) + 1
    for events in by_round.values():
        first = min(events, key=lambda event: event["time_in_round_in_ms"])
        first_bloods[first["killer"]["puuid"]] = first_bloods.get(first["killer"]["puuid"], 0) + 1
        first_deaths[first["victim"]["puuid"]] = first_deaths.get(first["victim"]["puuid"], 0) + 1
    scores = [p["stats"]["score"] for p in players]
    tracked = _build_tracked(detail, players, players, 20, kills_per_round, first_bloods, first_deaths,
                             max(scores), min(scores))
    return {item["p"]["puuid"]: item["tags"] for item in tracked}


def test_baited_operator_and_planter_tags():
    players = [_tag_player(i) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]
    kills = [_kill(r, "Blue-0", "Red-1", time=5_000) for r in range(4)]
    kills += [_kill(r, "Red-2", f"Blue-{r % 5}", weapon="Operator", time=20_000) for r in range(8)]
    rounds = [{"id": r, "plant": {"player": {"puuid": "Red-3"}}} for r in range(4)]

    tags = _tags_for(players, enemies, kills, rounds)

    assert "BAITED" in tags["Red-1"]
    assert "OPERATOR" in tags["Red-2"]
    assert "PLANTER" in tags["Red-3"]


def test_operator_needs_enough_operator_kills():
    players = [_tag_player(i) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]
    kills = [_kill(r, "Red-2", "Blue-0", weapon="Operator") for r in range(5)]

    tags = _tags_for(players, enemies, kills)

    assert not any("OPERATOR" in player_tags for player_tags in tags.values())


def test_eco_fraud_counts_kills_against_a_much_cheaper_loadout():
    players = [_tag_player(i) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]
    rounds = [{"id": r, "stats": [
        {"player": {"puuid": "Red-4"}, "economy": {"loadout_value": 4700}},
        {"player": {"puuid": f"Blue-{r}"}, "economy": {"loadout_value": 800}},
    ]} for r in range(3)]
    kills = [_kill(r, "Red-4", f"Blue-{r}") for r in range(3)]

    tags = _tags_for(players, enemies, kills, rounds)

    assert "ECO FRAUD" in tags["Red-4"]


def test_eco_fraud_ignores_kills_made_on_a_cheap_buy():
    players = [_tag_player(i) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]
    rounds = [{"id": r, "stats": [
        {"player": {"puuid": "Red-4"}, "economy": {"loadout_value": 800}},
        {"player": {"puuid": f"Blue-{r}"}, "economy": {"loadout_value": 4700}},
    ]} for r in range(3)]
    kills = [_kill(r, "Red-4", f"Blue-{r}") for r in range(3)]

    tags = _tags_for(players, enemies, kills, rounds)

    assert "ECO FRAUD" not in tags["Red-4"]


def test_knife_tag_is_shared_and_counts_multiple_knife_kills():
    players = [_tag_player(i) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]
    kills = [_kill(0, "Red-0", "Blue-0", weapon="Melee"), _kill(1, "Red-0", "Blue-1", weapon="Knife"),
             _kill(2, "Red-3", "Blue-2", weapon="Melee"), _kill(3, "Blue-0", "Red-4", weapon="Melee")]

    tags = _tags_for(players, enemies, kills)

    assert "KNIFE x2" in tags["Red-0"]
    assert "KNIFE" in tags["Red-3"]
    assert not any(tag == "KNIFE" or tag.startswith("KNIFE x") for tag in tags["Red-4"])
    assert "KNIFED" in tags["Red-4"]  # knifed by Blue-0


def test_exit_farmer_goes_to_most_kills_in_lost_rounds():
    players = [_tag_player(i) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]
    rounds = [{"id": r, "winning_team": "Blue" if r < 6 else "Red"} for r in range(10)]
    kills = [_kill(r, "Red-2", f"Blue-{r % 5}") for r in range(6)]
    kills += [_kill(r, "Red-1", f"Blue-{r % 5}") for r in range(6, 10) for _ in range(2)]

    tags = _tags_for(players, enemies, kills, rounds)

    assert "EXIT FARMER" in tags["Red-2"]
    assert "EXIT FARMER" not in tags["Red-1"]


def test_exit_farmer_needs_enough_lost_round_kills():
    players = [_tag_player(i) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]
    rounds = [{"id": r, "winning_team": "Blue"} for r in range(5)]
    kills = [_kill(r, "Red-2", f"Blue-{r}") for r in range(5)]

    tags = _tags_for(players, enemies, kills, rounds)

    assert not any("EXIT FARMER" in player_tags for player_tags in tags.values())


def test_team_killer_prefers_actual_team_kills_over_friendly_fire():
    players = [_tag_player(i, friendly_fire=300 if i == 1 else 0) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]

    assert "TEAM KILLER" in _tags_for(players, enemies)["Red-1"]
    tags = _tags_for(players, enemies, [_kill(3, "Red-0", "Red-4")])
    assert "TEAM KILLER" in tags["Red-0"]
    assert "TEAM KILLER" not in tags["Red-1"]


def test_body_shooter_goes_to_lowest_headshot_rate():
    players = [_tag_player(i, headshots=2 if i == 3 else 10) for i in range(5)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]

    tags = _tags_for(players, enemies)

    assert "BODY SHOOTER" in tags["Red-3"]
    assert sum("BODY SHOOTER" in player_tags for player_tags in tags.values()) == 1


def test_passenger_is_the_next_low_scorer_after_the_lvp():
    scores = [5000, 4800, 4600, 2600, 2000]
    players = [_tag_player(i, score=score) for i, score in enumerate(scores)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]

    tags = _tags_for(players, enemies)

    assert "LVP" in tags["Red-4"]
    assert "PASSENGER" in tags["Red-3"]
    assert "PASSENGER" not in tags["Red-4"]


def test_passenger_skipped_when_only_the_lvp_scored_low():
    scores = [5000, 4800, 4600, 4400, 2000]
    players = [_tag_player(i, score=score) for i, score in enumerate(scores)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]

    tags = _tags_for(players, enemies)

    assert not any("PASSENGER" in player_tags for player_tags in tags.values())


def test_passenger_goes_to_tied_low_scorer_who_missed_lvp():
    scores = [5000, 4800, 4600, 2000, 2000]
    players = [_tag_player(i, score=score) for i, score in enumerate(scores)]
    enemies = [_tag_player(i, team="Blue") for i in range(5)]

    tags = _tags_for(players, enemies)

    lvp = [puuid for puuid, player_tags in tags.items() if "LVP" in player_tags]
    passenger = [puuid for puuid, player_tags in tags.items() if "PASSENGER" in player_tags]
    assert len(lvp) == 1 and len(passenger) == 1
    assert {lvp[0], passenger[0]} == {"Red-3", "Red-4"}


def test_schedule_renderer_returns_png_without_external_art():
    buffer = render_schedule_card(
        {
            "stage": "Stage One",
            "note": "Queue Tuesday",
            "weeks": [{"label": "Week 1", "map": "Ascent", "start": "2026-11-01", "end": "2026-11-01"}],
        },
        {},
        "2026-11-01",
    )

    width, height = _png_size(buffer)
    assert width == 1200
    assert height > 128


def test_lineup_renderer_returns_a_five_slot_card():
    buffer = render_lineup_card("Ascent", "Week 1", [], {})

    width, height = _png_size(buffer)
    assert width == 900
    assert height == 156 + 5 * 112 + 24


def test_player_history_renders_grouped_rows_with_missing_icons():
    rows = [
        {"started": "2026-11-03T12:00:00Z", "map": "Haven", "agent": "Sova", "won": True,
         "score": "13-9", "k": 14, "d": 10, "a": 5, "acs": 200, "adr": 145, "hs": 25},
        {"started": "2026-11-02T12:00:00Z", "map": "Abyss", "agent": "Clove", "won": None,
         "score": "12-12", "k": 10, "d": 10, "a": 8, "acs": 170, "adr": 120, "hs": 20},
    ]

    width, height = _png_size(render_player_history("Player", "EU", "competitive", rows, {}))

    assert width == 1200
    assert height == 364 + 2 * (46 + 106) + 20


def test_player_rank_summary_uses_latest_act_and_preserves_zero_rr():
    mmr = {"current": {"tier": {"id": 16, "name": "Platinum 2"}, "rr": 0},
           "seasonal": [
               {"season": {"short": "e9a3"}, "wins": 20, "games": 30},
               {"season": {"short": "e10a1"}, "wins": 6, "games": 14},
           ]}
    assert rank_summary(mmr) == {"rank": "Platinum 2", "tier_id": 16, "rr": 0,
                                 "act": "E10A1", "wins": 6, "games": 14}
    assert rank_summary(None)["rank"] == "Unavailable"


def test_help_card_grows_to_fit_long_commands_and_descriptions():
    short = [("Players", [("/rank [member]", "Show rank")])]
    long = [("Players", [("/rank " + "[option] " * 20, "Long description " * 60)])]

    short_width, short_height = _png_size(render_help_card(short))
    long_width, long_height = _png_size(render_help_card(long))

    assert short_width == long_width == 1200
    assert long_height > short_height


def test_tactical_map_renders_markers_and_missing_map_is_optional(tmp_path):
    assert render_playbook_card("Ascent", "attack", "Execute", tmp_path / "missing.png", []) is None
    background = Image.new("RGBA", (600, 400), (70, 70, 75, 255))
    markers = [{"kind": "player", "x": 0.2, "y": 0.5, "label": "1"},
               {"kind": "smoke", "x": 0.7, "y": 0.5, "label": ""},
               {"kind": "path", "x": 0.2, "y": 0.5, "points": [[0.2, 0.5], [0.7, 0.5]]}]
    assert _png_size(render_playbook_card("Ascent", "attack", "Execute", background, markers)) == (1024, 1080)


def test_strategy_card_grows_for_description_and_keeps_uploaded_image():
    short = {"name": "A Execute", "map": "Haven", "side": "attack"}
    data = BytesIO()
    Image.new("RGB", (400, 200), (120, 80, 40)).save(data, "PNG")
    _, short_height = _png_size(render_strategy_card(short, "Short description"))
    image = render_strategy_card(short, "Long description " * 80, data.getvalue())
    width, height = _png_size(image)
    assert width == 1200
    assert height > short_height + 200


def test_rank_change_renderer_returns_fixed_size_png_without_icons():
    buffer = draw_rank_change_card("Player", "Gold 3", "Platinum 1", "up", None, None)

    assert _png_size(buffer) == (1200, 500)


def test_match_card_renderer_accepts_missing_icons_and_map_art():
    players = [
        {
            "puuid": f"player-{index}", "name": f"Player {index}", "tag": "EU", "team_id": "Red",
            "stats": {"kills": 10, "deaths": 8, "assists": 4, "score": 2100,
                      "headshots": 10, "bodyshots": 20, "legshots": 10,
                      "damage": {"dealt": 1800}},
        }
        for index in range(5)
    ]
    representative = players[0]
    detail = {
        "metadata": {"map": {"name": "Ascent"}, "game_length_in_ms": 1_200_000,
                     "started_at": "2026-11-01T12:00:00Z"},
        "teams": [{"team_id": "Red", "won": True, "rounds": {"won": 13, "lost": 8}}],
        "players": players,
        "kills": [],
        "rounds": [],
    }

    buffer = draw_play_result(detail, players, players, representative, None)

    width, height = _png_size(buffer)
    assert width == 1200
    assert height > 650  # five teammate cards render across three rows


def test_round_results_follow_round_order_and_need_every_round():
    rounds = [{"id": 2, "winning_team": "Blue"}, {"id": 0, "winning_team": "Red"}, {"id": 1, "winning_team": "red"}]
    assert _round_results({"rounds": rounds}, "Red", 2, 1) == [True, True, False]
    assert _round_results({"rounds": rounds}, "Red", 3, 1) is None  # a round is missing
    assert _round_results({"rounds": rounds}, "Red", 1, 2) is None  # winners don't add up to the score
    assert _round_results({"rounds": rounds[:2] + [{"id": 2}]}, "Red", 2, 1) is None


def test_match_card_adds_round_strip_when_rounds_match_the_score():
    players = [{"puuid": f"p{index}", "name": f"Player {index}", "tag": "EU", "team_id": "Red",
                "stats": {"kills": 10, "deaths": 8, "assists": 4, "score": 2100, "headshots": 10,
                          "bodyshots": 20, "legshots": 10, "damage": {"dealt": 1800}}} for index in range(5)]
    detail = {"metadata": {"map": {"name": "Ascent"}, "game_length_in_ms": 1_200_000,
                           "started_at": "2026-11-01T12:00:00Z"},
              "teams": [{"team_id": "Red", "won": True, "rounds": {"won": 13, "lost": 8}}],
              "players": players, "kills": [], "rounds": []}
    _, plain_height = _png_size(draw_play_result(detail, players, players, players[0], None))
    detail["rounds"] = [{"id": index, "winning_team": "Red" if index % 3 else "Blue"} for index in range(21)]
    detail["rounds"][19]["winning_team"] = "Blue"  # 13 won, 8 lost, final round won
    _, strip_height = _png_size(draw_play_result(detail, players, players, players[0], None))
    assert strip_height == plain_height + ROUND_STRIP_HEIGHT


def _roast_lobby():
    return [_tag_player(i) for i in range(5)], [_tag_player(i, team="Blue") for i in range(5)]


def test_knifed_is_shared_by_everyone_an_enemy_knifes():
    players, enemies = _roast_lobby()
    kills = [_kill(0, "Blue-0", "Red-1", weapon="Melee"), _kill(1, "Blue-2", "Red-3", weapon="Knife"),
             _kill(2, "Blue-2", "Red-3", weapon="Melee")]

    tags = _tags_for(players, enemies, kills)

    assert "KNIFED" in tags["Red-1"]
    assert "KNIFED x2" in tags["Red-3"]


def test_choker_goes_to_the_last_player_alive_in_lost_rounds():
    players, enemies = _roast_lobby()
    kills, rounds = [], []
    for r in range(4):
        kills += [_kill(r, "Blue-0", f"Red-{i}", time=1_000 * (n + 1)) for n, i in enumerate((0, 1, 3, 4, 2))]
        rounds.append({"id": r, "winning_team": "Blue"})

    tags = _tags_for(players, enemies, kills, rounds)

    assert "CHOKER" in tags["Red-2"]


def test_tourist_counts_rounds_without_a_kill_or_assist():
    players, enemies = _roast_lobby()
    kills = [_kill(r, f"Red-{i}", f"Blue-{i}", time=10_000 + i) for r in range(20) for i in range(4)]
    kills += [_kill(r, "Red-4", "Blue-4", time=30_000) for r in range(5)]

    tags = _tags_for(players, enemies, kills)
    assert "TOURIST" in tags["Red-4"]
    assert not any("TOURIST" in tags[f"Red-{i}"] for i in range(4))

    assists = [dict(_kill(r, "Red-0", "Blue-0", time=40_000), assistants=[{"puuid": "Red-4"}]) for r in range(5, 15)]
    assert "TOURIST" not in _tags_for(players, enemies, kills + assists)["Red-4"]


def test_tourist_is_not_guessed_without_kill_events():
    players, enemies = _roast_lobby()

    assert not any("TOURIST" in tags for tags in _tags_for(players, enemies).values())


def test_afk_tag_uses_afk_rounds_from_behaviour():
    players, enemies = _roast_lobby()
    players[3]["behavior"]["afk_rounds"] = 2

    tags = _tags_for(players, enemies)

    assert "AFK" in tags["Red-3"]
    assert not any("AFK" in tags[f"Red-{i}"] for i in (0, 1, 2, 4))


def test_kill_stealer_needs_two_other_teammates_on_the_assist():
    players, enemies = _roast_lobby()
    kills = [dict(_kill(r, "Red-1", f"Blue-{r % 5}"), assistants=[{"puuid": "Red-0"}, {"puuid": "Red-2"}])
             for r in range(4)]
    kills += [dict(_kill(r, "Red-3", f"Blue-{r % 5}"), assistants=[{"puuid": "Red-0"}, {"puuid": "Red-3"}])
              for r in range(4, 9)]

    tags = _tags_for(players, enemies, kills)

    assert "KILL STEALER" in tags["Red-1"]
    assert "KILL STEALER" not in tags["Red-3"]  # only one other teammate assisted


def test_martyr_counts_first_deaths_in_rounds_the_team_won():
    players, enemies = _roast_lobby()
    kills, rounds = [], []
    for r in range(5):
        victim = "Red-2" if r < 3 else "Red-4"
        kills += [_kill(r, "Blue-0", victim, time=5_000), _kill(r, "Red-0", "Blue-0", time=9_000)]
        rounds.append({"id": r, "winning_team": "Red" if r < 3 else "Blue"})
    kills += [_kill(r, "Blue-1", "Red-4", time=5_000) for r in range(5, 8)]  # first deaths in lost rounds
    rounds += [{"id": r, "winning_team": "Blue"} for r in range(5, 8)]

    tags = _tags_for(players, enemies, kills, rounds)

    assert "MARTYR" in tags["Red-2"]
    assert "MARTYR" not in tags["Red-4"]
