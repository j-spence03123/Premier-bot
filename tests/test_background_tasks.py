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
@pytest.mark.parametrize("smurf", [False, True])
async def test_matchfeed_posts_new_match_before_checking_current_ranks(monkeypatch, smurf):
    monkeypatch.setattr(background_tasks.asyncio, "sleep", AsyncMock())
    order = []
    player = {"puuid": "one", "name": "Friend", "tag": "EUW", "team_id": "Red"}
    detail = {"players": [player], "teams": [{"team_id": "Red", "won": True, "rounds": {"won": 13, "lost": 7}}]}
    feeds = {"1": {"channel_id": 2, "started_at": "2026-11-01T00:00:00Z",
                   "squad_lore": {"the closer": {"label": "The Closer", "kind": "nickname", "trigger": "win",
                                                  "member_id": "1"}}}}
    main = {"name": "Friend", "tag": "EUW"}
    if smurf:
        main = {"name": "Main", "tag": "EUW", "smurfs": [main]}

    async def api(path, ttl, **params):
        if "stored-matches" in path:
            order.append("history")
            if "/Main/" in path:
                return []
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
    match_image = AsyncMock(return_value=SimpleNamespace(fp=BytesIO(b"image"), squad_callback_used=True))
    record_clutches = Mock()
    await background_tasks.matchfeed_loop(
        client=client, load_matchfeeds=lambda: feeds,
        load_accounts=lambda: {"1": main},
        load_rank_states=dict, save_rank_states=Mock(), cached_api=api,
        cached=AsyncMock(return_value=detail), match_detail=AsyncMock(), parse_time=parse_time,
        play_match_image=match_image,
        rank_change_image=AsyncMock(), save_matchfeed_progress=Mock(), AFFINITY="eu",
        record_clutches=record_clutches,
    )
    match_id, _, recorded_detail, linked_keys = record_clutches.call_args.args
    assert (match_id, recorded_detail) == ("match", detail) and "friend#euw" in linked_keys
    account_count = 2 if smurf else 1
    assert order == ["history"] * account_count + ["post"] + ["rank"] * account_count
    assert match_image.await_args.kwargs["summary_players"][0]["is_smurf"] is smurf
    assert match_image.await_args.kwargs["squad_context"]["callback"]["player"] == "Friend"
    assert feeds["1"]["match_counts"]["squad_memory"]["used"] == {"the closer": 1}


@pytest.mark.asyncio
async def test_rank_up_card_gets_match_and_act_context(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(background_tasks.asyncio, "sleep", AsyncMock())
    now = datetime.now(timezone.utc)
    stamp = lambda hours: int((now - timedelta(hours=hours)).timestamp())  # noqa: E731
    stored = [{"meta": {"id": "match", "started_at": (now - timedelta(minutes=50)).isoformat(),
                        "map": {"name": "Bind"}},
               "stats": {"team": "Red", "kills": 20, "deaths": 10, "score": 5000}, "teams": {"red": 13, "blue": 8}}]
    history = [{"date_raw": stamp(90), "currenttier": 17, "season_id": "old", "match_id": "a"},
               {"date_raw": stamp(40), "currenttier": 15, "season_id": "new", "match_id": "b"},
               {"date_raw": stamp(20), "currenttier": 14, "season_id": "new", "match_id": "c"}]

    async def api(path, ttl, **params):
        if "stored-matches" in path:
            return stored
        if "mmr-history" in path:
            return history
        return {"current": {"tier": {"id": 15, "name": "Platinum 1"}, "rr": 12, "last_change": 21}}

    saved = Mock()
    rank_image = AsyncMock(return_value=SimpleNamespace(fp=BytesIO(b"rank")))
    sent = []
    guild = SimpleNamespace(id=1, get_member=Mock(return_value=object()))
    client = Mock(wait_until_ready=AsyncMock(), is_closed=Mock(side_effect=[False, True]),
                  get_guild=Mock(return_value=guild),
                  get_channel=Mock(return_value=SimpleNamespace(send=AsyncMock(side_effect=lambda **kw: sent.append(kw)))))
    feeds = {"1": {"channel_id": 2, "started_at": "2026-11-01T00:00:00Z", "seen": ["match"]}}
    await background_tasks.matchfeed_loop(
        client=client, load_matchfeeds=lambda: feeds, load_accounts=lambda: {"1": {"name": "Friend", "tag": "EUW"}},
        load_rank_states=lambda: {"friend#euw": {"tier_id": 14, "tier_name": "Gold 3", "rr": 90}},
        save_rank_states=saved, cached_api=api, cached=AsyncMock(), match_detail=AsyncMock(), parse_time=parse_time,
        play_match_image=AsyncMock(), rank_change_image=rank_image, save_matchfeed_progress=Mock(), AFFINITY="eu",
    )
    assert rank_image.await_args.kwargs["context"] == "After a 13–8 win on Bind  ·  Second time in Platinum this act"
    state = saved.call_args.args[0]["friend#euw"]
    assert state["tier_id"] == 15 and state["act"] == {"season": "new", "complete": True, "groups": {"4": 2}}
    assert sent[0]["content"].endswith("ranked up!")
