from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from graphics.weekly_recap import draw_weekly_recap
from services.weekly_recap import (RECAP_ZONE, build_week, completed_week, local_summary, premier_results,
                                   run_weekly_recap, top_games, week_end_at_or_before, window_games,
                                   window_rank_ups, window_rr)

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


def test_rank_ups_inside_week_ignore_act_resets_and_combine_steps():
    history = [
        mmr(START - timedelta(hours=2), 10, 11, "Silver 3", 890),
        mmr(START + timedelta(days=1), 20, 12, "Gold 1", 910),
        mmr(START + timedelta(days=2), 25, 13, "Gold 2", 1010),
        mmr(START + timedelta(days=3), 0, 15, "Platinum 1", 1200, season="new"),
    ]
    assert window_rank_ups(history, START, END) == [
        {"from_id": 11, "from": "Silver 3", "to_id": 13, "to": "Gold 2"}]
    baseline = {"tier_id": 12, "tier_name": "Gold 1", "at": START.isoformat()}
    current = {"tier_id": 13, "tier_name": "Gold 2"}
    assert window_rank_ups([], START, END, baseline, current)[0]["to"] == "Gold 2"


def test_games_and_top_three_are_limited_to_the_week():
    rows = [stored("old", START - timedelta(minutes=1)), stored("a", START + timedelta(hours=1), score=6000),
            stored("b", START + timedelta(days=2), score=4000, red=5, blue=13)]
    games = window_games(rows, START, END)
    assert [game["match_id"] for game in games] == ["a", "b"]
    players = [{"name": "Kevin", "games": games},
               {"name": "Spam", "games": window_games([stored("c", START + timedelta(days=3), score=7000)],
                                                       START, END)}]
    best = top_games(players)
    assert [(game["player"], game["match_id"]) for game in best] == [("Spam", "c"), ("Kevin", "a"), ("Kevin", "b")]


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
        {"name": "Kevin", "games": games, "rr": 35, "partial": False, "rank": "Gold 2",
         "rank_ups": [{"from_id": 12, "from": "Gold 1", "to_id": 13, "to": "Gold 2"}]},
        {"name": "Spam", "smurf": True, "games": games[:1], "rr": -12, "partial": True, "rank": "Silver 1"},
        {"name": "Idle", "games": [], "rr": 0, "partial": False, "rank": None},
    ]
    result = premier_results([({"started_at": (START + timedelta(days=4)).isoformat()},
                               {"won": False, "score": "9-13", "map": "Lotus", "them": "Rivals",
                                "started": (START + timedelta(days=4)).isoformat()})], START, END) if premier else None
    return build_week(players, START, END, result)


def test_build_week_and_local_summary():
    week = sample_week()
    assert [player["name"] for player in week["players"]] == ["Kevin", "Idle", "Spam"]
    assert week["squad"] == {"games": 2, "wins": 1, "losses": 1}
    assert week["rank_ups"][0]["player"] == "Kevin"
    text = local_summary(week)
    assert "Kevin climbed the most with +35 RR" in text and "Premier went 0W 1L" in text
    assert "Quiet week" in local_summary(build_week([], START, END))


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
        load_accounts=lambda: {"10": {"name": "Kevin", "tag": "EU"}},
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
    assert state["baselines"]["kevin#eu"]["elo"] == 922
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


def test_card_bytes_are_png():
    week = sample_week()
    assert draw_weekly_recap(week).getvalue()[:8] == BytesIO(b"\x89PNG\r\n\x1a\n").getvalue()
