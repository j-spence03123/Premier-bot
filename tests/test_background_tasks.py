from unittest.mock import AsyncMock, Mock

import pytest

from services import background_tasks


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
