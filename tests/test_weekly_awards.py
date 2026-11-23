from datetime import datetime, timedelta

from PIL import Image

from graphics.weekly_recap import draw_weekly_recap
from services.clutch_store import match_clutches, player_clutches, record_match
from services.weekly_awards import build_awards
from services.weekly_recap import RECAP_ZONE, build_week, window_rank_swing

START = datetime(2026, 11, 22, 20, tzinfo=RECAP_ZONE)
END = START + timedelta(days=7)


def clutch_detail():
    """Ana is left alone against five twice: loses round 1, wins round 2."""
    players = [{"puuid": f"r{i}", "name": "Ana" if i == 0 else f"Red{i}", "tag": "EU", "team_id": "Red"}
               for i in range(5)]
    players += [{"puuid": f"b{i}", "name": f"Blue{i}", "tag": "EU", "team_id": "Blue"} for i in range(5)]
    kills = []
    for round_number in (0, 1):
        kills += [{"round": round_number, "time_in_round_in_ms": 1000 * i, "victim": {"puuid": f"r{i}"},
                   "killer": {"puuid": "b0"}} for i in range(1, 5)]
    rounds = [{"id": 0, "winning_team": "Blue"}, {"id": 1, "winning_team": "Red"}]
    return {"players": players, "kills": kills, "rounds": rounds}


def test_clutches_are_recorded_for_linked_players_and_old_matches_pruned():
    detail = clutch_detail()
    assert match_clutches(detail, {"ana#eu"}) == {"ana#eu": [1, 1]}
    now = END
    store = {"old": {"started": (now - timedelta(days=15)).isoformat(), "players": {"ana#eu": [0, 1]}}}
    record_match(store, "m1", now - timedelta(days=1), match_clutches(detail, {"ana#eu"}), now)
    assert set(store) == {"m1"}


def test_player_clutches_fill_gaps_from_cached_details_only():
    store = {"m1": {"started": START.isoformat(), "players": {"ana#eu": [0, 3]}}}
    details = {"m2": clutch_detail()}
    totals = player_clutches("ana#eu", ["m1", "m2", "m3"], store, details.get)
    assert totals == {"won": 1, "lost": 4, "games": 2}  # m3 has no data and is not counted


def mmr(when, tier, name, season="act"):
    return {"date_raw": int(when.timestamp()), "mmr_change_to_last_game": 0, "currenttier": tier,
            "currenttierpatched": name, "elo": 0, "season_id": season}


def test_rank_swing_finds_a_rank_gained_and_lost_in_the_week():
    tiers = [(14, "Gold 3")] * 3 + [(15, "Platinum 1")] * 3 + [(14, "Gold 3")]
    history = [mmr(START - timedelta(hours=1), 14, "Gold 3")]
    history += [mmr(START + timedelta(hours=i + 1), tier, name) for i, (tier, name) in enumerate(tiers)]
    assert window_rank_swing(history, START, END) == {
        "peak": "Platinum 1", "peak_game": 4, "end": "Gold 3", "drop_game": 7}
    kept = history[:-1]
    assert window_rank_swing(kept, START, END) is None


def games(count, *, kd=1.0, acs=200, adr=130, hs=20, wins=None, results=None):
    results = results or [index < (count // 2 if wins is None else wins) for index in range(count)]
    return [{"match_id": f"g{index}-{acs}-{hs}", "started_at": START + timedelta(hours=index + 1), "won": won,
             "k": round(15 * kd), "d": 15, "a": 3, "acs": acs, "adr": adr, "hs": hs, "agent": "Jett",
             "agent_id": "jett-id", "map": "Bind", "score": "13-9"} for index, won in enumerate(results)]


def player(name, rr, game_rows, **extra):
    return {"name": name, "riot_key": f"{name}#eu".casefold(), "rr": rr, "partial": False, "smurf": False,
            "games": game_rows, "rank_changes": [], **extra}


def squad():
    return [
        player("Kevin", 64, games(13, kd=1.33, acs=252, adr=150, hs=27, wins=8)),
        player("Spam", 21, games(9, kd=1.06, acs=228, adr=156, hs=11, wins=6)),
        player("Emilia", -71, games(11, kd=0.77, acs=171, adr=118, hs=19,
                                    results=[True, False, False, False, False, False, False, True, False, True, False])),
        player("broodje", 8, games(10, kd=0.8, acs=168, adr=121, hs=24),
               clutch={"won": 0, "lost": 9, "games": 10}),
        player("Wilbo", 0, games(2)),
        {**player("Kevin", 90, games(20, kd=3, acs=400, adr=250, hs=50)), "smurf": True},
    ]


def test_player_of_the_week_leads_the_most_stats_among_main_accounts():
    awards = build_awards(squad())
    potw = awards["player_of_the_week"]
    assert potw["player"] == "Kevin" and potw["games"] == 13
    assert potw["leads"] == ["rr", "kd", "acs", "hs"]
    assert [stat["lead"] for stat in potw["stats"]] == [True, True, True, False, True, False]
    assert potw["line"].startswith("+64 RR and nobody else got past +21.")


def test_each_roast_award_and_player_is_used_once():
    by_player = {award["player"]: award for award in build_awards(squad())["awards"]}
    assert "Kevin" not in by_player
    assert by_player["Emilia"]["award"] == "ON TILT" and by_player["Emilia"]["value"] == "6"
    assert by_player["broodje"]["award"] == "CLUTCH ZERO" and by_player["broodje"]["value"] == "0/9"
    assert by_player["Wilbo"]["award"] == "CAMEO"
    assert by_player["Spam"]["award"] == "BODY SHOOTER"  # worst headshot rate, not just the last one left
    assert len({award["award"] for award in by_player.values()}) == len(by_player)


def test_no_awards_without_two_players_with_enough_games():
    assert build_awards([player("Solo", 10, games(8)), player("Cameo", 0, games(2))]) is None


def test_weekly_card_draws_awards_section():
    week = build_week(squad(), START, END)
    assert week["awards"]["player_of_the_week"]["player"] == "Kevin"
    with_awards = Image.open(draw_weekly_recap(week, agent_icons={"jett": Image.new("RGBA", (96, 96), "red")}))
    without = Image.open(draw_weekly_recap({**week, "awards": None}))
    assert with_awards.height > without.height + 600
