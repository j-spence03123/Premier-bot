from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from graphics.weekly_recap import draw_weekly_recap
import services.weekly_recap as weekly_recap
from services.weekly_recap import (PREFETCH_MAX_LEAD, RECAP_ZONE, build_week, collect_player_data, completed_week,
                                   local_summary, next_week_end, prefetch_lead, premier_results, run_weekly_recap,
                                   top_game_map_art, top_games, week_end_at_or_before, window_games,
                                   window_rank_changes, window_rr)

START = datetime(2026, 11, 8, 20, tzinfo=RECAP_ZONE)
END = datetime(2026, 11, 15, 20, tzinfo=RECAP_ZONE)


def mmr(when, change, tier, name, elo, season="act"):
    return {"date_raw": int(when.timestamp()), "mmr_change_to_last_game": change, "currenttier": tier,
            "currenttierpatched": name, "elo": elo, "season_id": season, "match_id": str(when)}


def stored(match_id, when, kills=20, deaths=10, score=5400, red=13, blue=7, team="Red", agent="Jett", map_name="Bind"):
    return {"meta": {"id": match_id, "started_at": when.isoformat(), "map": {"name": map_name}},
            "stats": {"team": team, "kills": kills, "deaths": deaths, "assists": 4, "score": score,
                      "character": {"name": agent}, "shots": {"head": 10, "body": 30, "leg": 0},
                      "damage": {"made": 3000}},
            "teams": {"red": red, "blue": blue}}


def test_week_windows_follow_sunday_eight_pm_uk_time():
    before = datetime(2026, 11, 15, 19, 59, tzinfo=RECAP_ZONE)
    after = datetime(2026, 11, 15, 20, 0, tzinfo=RECAP_ZONE)
    assert week_end_at_or_before(before) == datetime(2026, 11, 8, 20, tzinfo=RECAP_ZONE)
    assert completed_week(after) == (START, END)
    assert completed_week(datetime(2026, 11, 18, 9, tzinfo=timezone.utc)) == (START, END)
    # The window keeps 20:00 local time across the October clock change.
    start, end = completed_week(datetime(2026, 10, 25, 21, tzinfo=RECAP_ZONE))
    assert (start.hour, end.hour) == (20, 20)
    assert end.astimezone(timezone.utc) - start.astimezone(timezone.utc) == timedelta(days=7, hours=1)


def test_rr_uses_history_when_it_covers_the_whole_week():
    history = [
        mmr(START - timedelta(hours=1), 18, 12, "Gold 1", 918),
        mmr(START + timedelta(days=1), 20, 12, "Gold 1", 938),
        mmr(START + timedelta(days=2), -15, 12, "Gold 1", 923),
        mmr(END + timedelta(minutes=5), 25, 12, "Gold 1", 948),
    ]
    assert window_rr(history, START, END) == {"rr": 5, "partial": False}
    assert window_rr([], START, END) == {"rr": 0, "partial": False}


def test_rr_falls_back_to_saved_rating_then_marks_partial():
    history = [mmr(START + timedelta(days=5), 20, 12, "Gold 1", 950)]
    baseline = {"elo": 900, "at": START.isoformat()}
    assert window_rr(history, START, END, baseline, {"elo": 950}) == {"rr": 50, "partial": False}
    late = {"elo": 900, "at": (START + timedelta(days=1)).isoformat()}
    assert window_rr(history, START, END, late, {"elo": 950}) == {"rr": 20, "partial": True}


def test_rank_changes_inside_week_ignore_act_resets_and_combine_steps():
    history = [
        mmr(START - timedelta(hours=2), 10, 11, "Silver 3", 890),
        mmr(START + timedelta(days=1), 20, 12, "Gold 1", 910),
        mmr(START + timedelta(days=2), 25, 13, "Gold 2", 1010),
        mmr(START + timedelta(days=3), 0, 15, "Platinum 1", 1200, season="new"),
    ]
    assert window_rank_changes(history, START, END) == [
        {"from_id": 11, "from": "Silver 3", "to_id": 13, "to": "Gold 2", "direction": "up"}]
    baseline = {"tier_id": 12, "tier_name": "Gold 1", "at": START.isoformat()}
    current = {"tier_id": 13, "tier_name": "Gold 2"}
    assert window_rank_changes([], START, END, baseline, current)[0]["to"] == "Gold 2"


def test_deranks_are_reported_and_round_trips_are_not():
    down = [mmr(START - timedelta(hours=1), 5, 13, "Gold 2", 1005),
            mmr(START + timedelta(days=1), -20, 12, "Gold 1", 985)]
    assert window_rank_changes(down, START, END) == [
        {"from_id": 13, "from": "Gold 2", "to_id": 12, "to": "Gold 1", "direction": "down"}]
    round_trip = down + [mmr(START + timedelta(days=2), 25, 13, "Gold 2", 1010)]
    assert window_rank_changes(round_trip, START, END) == []
    baseline = {"tier_id": 13, "tier_name": "Gold 2", "at": START.isoformat()}
    assert window_rank_changes([], START, END, baseline, {"tier_id": 12, "tier_name": "Gold 1"})[0][
        "direction"] == "down"


def test_games_and_top_three_are_limited_to_the_week():
    rows = [stored("old", START - timedelta(minutes=1)), stored("a", START + timedelta(hours=1), score=6000),
            stored("b", START + timedelta(days=2), score=4000, red=5, blue=13)]
    games = window_games(rows, START, END)
    assert [game["match_id"] for game in games] == ["a", "b"]
    players = [{"name": "Player", "games": games},
               {"name": "Player2", "games": window_games([stored("c", START + timedelta(days=3), score=7000)],
                                                       START, END)}]
    best = top_games(players)
    assert [(game["player"], game["match_id"]) for game in best] == [("Player2", "c"), ("Player", "a"), ("Player", "b")]


def test_premier_section_is_omitted_without_games_this_week():
    entry = {"started_at": (START + timedelta(days=4)).isoformat(), "points_before": 100, "points_after": 200}
    summary = {"won": True, "score": "13-9", "map": "Lotus", "them": "Rivals", "started": entry["started_at"]}
    result = premier_results([(entry, summary)], START, END)
    assert (result["wins"], result["losses"], result["points"]) == (1, 0, 100)
    old = {**summary, "started": (START - timedelta(days=1)).isoformat()}
    assert premier_results([(entry, old), ({}, {"error": "x"})], START, END) is None


def sample_week(premier=True):
    games = window_games([stored("a", START + timedelta(hours=1), score=6000),
                          stored("b", START + timedelta(days=2), score=4000, red=5, blue=13)], START, END)
    players = [
        {"name": "Player", "games": games, "rr": 35, "partial": False, "rank": "Gold 2",
         "rank_changes": [{"from_id": 12, "from": "Gold 1", "to_id": 13, "to": "Gold 2", "direction": "up"}]},
        {"name": "Player2", "smurf": True, "games": games[:1], "rr": -12, "partial": True, "rank": "Silver 1",
         "rank_changes": [{"from_id": 9, "from": "Silver 2", "to_id": 8, "to": "Silver 1", "direction": "down"}]},
        {"name": "Player3", "games": [], "rr": 0, "partial": False, "rank": None},
    ]
    result = premier_results([({"started_at": (START + timedelta(days=4)).isoformat()},
                               {"won": False, "score": "9-13", "map": "Lotus", "them": "Rivals",
                                "started": (START + timedelta(days=4)).isoformat()})], START, END) if premier else None
    return build_week(players, START, END, result)


def test_build_week_and_local_summary():
    week = sample_week()
    assert [player["name"] for player in week["players"]] == ["Player", "Player3", "Player2"]
    assert week["squad"] == {"games": 2, "wins": 1, "losses": 1}
    assert [(c["player"], c["direction"]) for c in week["rank_changes"]] == [("Player", "up"), ("Player2", "down")]
    text = local_summary(week)
    assert "Player climbed the most with +35 RR" in text and "Premier went 0W 1L" in text
    assert "Rank ups for Player." in text and "Deranks for Player2." in text
    assert "Quiet week" in local_summary(build_week([], START, END))


def test_smurf_games_are_ranked_separately():
    week = sample_week()
    assert {game["player"] for game in week["top_games"]} == {"Player"}
    assert [game["player"] for game in week["smurf_top_games"]] == ["Player2"]
    assert build_week([], START, END)["smurf_top_games"] == []


@pytest.mark.parametrize("premier", [True, False])
def test_weekly_card_renders(premier):
    week = sample_week(premier)
    week["summary"] = local_summary(week)
    image = Image.open(draw_weekly_recap(week))
    assert image.width == 1200 and image.height > 600
    empty = build_week([], START, END)
    empty["summary"] = local_summary(empty)
    assert Image.open(draw_weekly_recap(empty)).height > 300


def fake_api(path, ttl, **params):
    when = START + timedelta(days=1)
    if "stored-matches" in path:
        return AsyncMock(return_value=[stored("a", when)])()
    if "mmr-history" in path:
        return AsyncMock(return_value=[mmr(START - timedelta(hours=1), 5, 12, "Gold 1", 900),
                                       mmr(when, 22, 12, "Gold 1", 922)])()
    return AsyncMock(return_value={"current": {"tier": {"id": 12, "name": "Gold 1"}, "rr": 22, "elo": 922}})()


@pytest.mark.asyncio
async def test_run_posts_once_per_week_and_saves_baselines():
    state = {}
    channel = SimpleNamespace(send=AsyncMock())
    guild = SimpleNamespace(id=1, get_member=Mock(return_value=object()))
    client = SimpleNamespace(get_guild=Mock(return_value=guild), get_channel=Mock(return_value=channel),
                             http_session=None)
    kwargs = dict(
        client=client, load_matchfeeds=lambda: {"1": {"channel_id": 5}},
        load_accounts=lambda: {"10": {"name": "Player", "tag": "EU"}},
        load_weekly_recaps=lambda: state, save_weekly_recaps=lambda value: state.update(value),
        cached_api=fake_api, history=AsyncMock(return_value=[]), load_summaries=AsyncMock(),
        affinity="eu", groq_api_key=None, groq_model="m", pace=0,
    )
    now = END.astimezone(timezone.utc) + timedelta(minutes=1)
    await run_weekly_recap(now=now, **kwargs)
    await run_weekly_recap(now=now + timedelta(minutes=1), **kwargs)
    assert channel.send.await_count == 1
    sent = channel.send.await_args.kwargs
    assert sent["content"].startswith("**Weekly recap**")
    assert sent["file"].filename == "weekly-recap-2026-11-15.png"
    assert state["guilds"]["1"]["last_week_end"] == END.isoformat()
    assert state["baselines"]["player#eu"]["elo"] == 922
    kwargs["load_summaries"].assert_not_called()  # no Premier games this week


@pytest.mark.asyncio
async def test_run_skips_weeks_that_ended_long_ago():
    client = SimpleNamespace(get_guild=Mock())
    load = Mock()
    await run_weekly_recap(client=client, now=END.astimezone(timezone.utc) + timedelta(days=2),
                           load_matchfeeds=load, load_accounts=load, load_weekly_recaps=load,
                           save_weekly_recaps=load, cached_api=None, history=None, load_summaries=None,
                           affinity="eu", groq_api_key=None, groq_model="m", pace=0)
    load.assert_not_called()


@pytest.mark.asyncio
async def test_previous_week_preview_uses_last_completed_week_without_saving():
    state = {}
    guild = SimpleNamespace(id=1, get_member=Mock(return_value=object()))
    file = await weekly_recap.preview_weekly_recap(
        guild, now=END.astimezone(timezone.utc) + timedelta(days=3), previous=True,
        load_accounts=lambda: {"10": {"name": "Player", "tag": "EU"}}, load_weekly_recaps=lambda: state,
        load_matchfeeds=lambda: {}, cached_api=fake_api, history=AsyncMock(return_value=[]),
        load_summaries=AsyncMock(), affinity="eu", http_session=None, groq_api_key=None, groq_model="m", pace=0)
    assert file.filename == "weekly-recap-2026-11-15.png"
    assert state == {}


def test_card_bytes_are_png():
    week = sample_week()
    assert draw_weekly_recap(week).getvalue()[:8] == BytesIO(b"\x89PNG\r\n\x1a\n").getvalue()


@pytest.mark.asyncio
async def test_pacing_only_waits_before_real_requests(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(weekly_recap.asyncio, "sleep", fake_sleep)
    accounts = {"10": {"name": "Player", "tag": "EU"}, "11": {"name": "Player2", "tag": "EU"}}
    common = dict(cached_api=fake_api, affinity="eu", start=START, end=END, baselines={}, pace=2.3)
    players = await collect_player_data(accounts, is_cached=lambda path, **params: True, **common)
    assert len(players) == 2 and sleeps == []
    # Uncached requests are spaced out; the very first one goes straight away.
    await collect_player_data(accounts, is_cached=lambda path, **params: False, **common)
    assert len(sleeps) == 5 and all(0 < delay <= 2.3 for delay in sleeps)


def test_prefetch_starts_early_enough_but_inside_cache_ttl():
    assert next_week_end(datetime(2026, 11, 15, 19, 55, tzinfo=RECAP_ZONE)) == END
    assert next_week_end(END) == END + timedelta(days=7)
    assert prefetch_lead(4) == timedelta(seconds=4 * 3 * 2.3 + 60)
    assert prefetch_lead(500) == PREFETCH_MAX_LEAD


@pytest.mark.asyncio
async def test_map_art_is_fetched_once_per_map_and_failures_are_skipped():
    games = [{"map": "Bind", "map_id": "b"}, {"map": "bind", "map_id": "b"}, {"map": "Lotus", "map_id": None}]
    calls = []

    async def map_art(map_id, map_name):
        calls.append(map_name)
        if map_name == "Lotus":
            raise RuntimeError("offline")
        return "/tmp/bind.jpg"

    assert await top_game_map_art(games, map_art) == {"bind": "/tmp/bind.jpg"}
    assert calls == ["Bind", "Lotus"]
    assert await top_game_map_art(games, None) == {}


def test_top_game_cards_show_map_art(tmp_path):
    art = tmp_path / "bind.png"
    Image.new("RGB", (640, 360), (200, 40, 40)).save(art)
    week = sample_week()
    plain = Image.open(draw_weekly_recap(week)).convert("RGB")
    with_art = Image.open(draw_weekly_recap(week, {"bind": art, "lotus": tmp_path / "missing.png"})).convert("RGB")
    assert plain.size == with_art.size and plain.tobytes() != with_art.tobytes()


@pytest.mark.asyncio
async def test_stored_matches_page_until_they_reach_the_week_start():
    from services.weekly_recap import _stored_matches, RequestPacer
    pages = {
        1: [stored(f"a{i}", END - timedelta(hours=i + 1)) for i in range(30)],
        2: [stored(f"b{i}", END - timedelta(days=2, hours=i)) for i in range(29)] + [stored("old", START - timedelta(hours=1))],
        3: [stored("never", START - timedelta(days=3))],
    }
    calls = []

    async def api(path, ttl, **params):
        calls.append(params.get("page", 1))
        return pages[params.get("page", 1)]

    rows = await _stored_matches(api, RequestPacer(0), None, "/stored", {"mode": "competitive", "size": 30}, START)
    assert calls == [1, 2]
    assert len(rows) == 60
    assert len(window_games(rows, START, END)) == 59
