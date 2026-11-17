from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services import background_tasks
from utils.formatting import parse_time


@pytest.mark.asyncio
async def test_background_pollers_run_one_empty_cycle(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(background_tasks.asyncio, "sleep", sleep)

    def client():
        return Mock(wait_until_ready=AsyncMock(), is_closed=Mock(side_effect=[False, True]))

    async_fn = AsyncMock()
    save = Mock()
    empty = Mock(return_value={})
    first = client()
    await background_tasks.queue_reminder_loop(
        client=first, load_queue_schedules=empty, build_lineup_reminder=async_fn,
        next_queue_start=Mock(), save_queue_schedules=save,
    )
    second = client()
    await background_tasks.play_session_loop(
        client=second, load_play_sessions=empty, load_matchfeeds=empty, load_accounts=empty,
        cached_api=async_fn, cached=async_fn, match_detail=async_fn, parse_time=Mock(),
        play_match_image=async_fn, save_play_sessions=save, AFFINITY="eu",
    )
    third = client()
    await background_tasks.matchfeed_loop(
        client=third, load_matchfeeds=empty, load_accounts=empty, load_rank_states=empty,
        save_rank_states=save, cached_api=async_fn, cached=async_fn, match_detail=async_fn,
        parse_time=Mock(), play_match_image=async_fn, rank_change_image=async_fn,
        save_matchfeed_progress=save, AFFINITY="eu",
    )
    for bot in (first, second, third):
        bot.wait_until_ready.assert_awaited_once()
    assert sleep.await_count == 3
    async_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_matchfeed_posts_new_match_before_checking_current_ranks(monkeypatch):
    monkeypatch.setattr(background_tasks.asyncio, "sleep", AsyncMock())
    order = []
    player = {"puuid": "one", "name": "Friend", "tag": "EUW", "team_id": "Red"}
    detail = {"players": [player], "teams": [{"team_id": "Red", "won": True}]}
    feeds = {"1": {"channel_id": 2, "started_at": "2026-11-01T00:00:00Z"}}

    async def api(path, ttl, **params):
        if "stored-matches" in path:
            order.append("history")
            return [{"meta": {"id": "match", "started_at": "2026-11-17T12:00:00Z"}}]
        if "mmr-history" in path:
            return []
        order.append("rank")
        return {"current": {"tier": {"id": 18, "name": "Diamond 1"}}}

    async def send(**kwargs):
        order.append("post")
        kwargs["file"].close()

    guild = SimpleNamespace(id=1, get_member=Mock(return_value=object()))
    client = Mock(wait_until_ready=AsyncMock(), is_closed=Mock(side_effect=[False, True]),
                  get_guild=Mock(return_value=guild),
                  get_channel=Mock(return_value=SimpleNamespace(send=send)))
    await background_tasks.matchfeed_loop(
        client=client, load_matchfeeds=lambda: feeds,
        load_accounts=lambda: {"1": {"name": "Friend", "tag": "EUW"}},
        load_rank_states=dict, save_rank_states=Mock(), cached_api=api,
        cached=AsyncMock(return_value=detail), match_detail=AsyncMock(), parse_time=parse_time,
        play_match_image=AsyncMock(return_value=SimpleNamespace(fp=BytesIO(b"image"))),
        rank_change_image=AsyncMock(), save_matchfeed_progress=Mock(), AFFINITY="eu",
    )
    assert order == ["history", "post", "rank"]
