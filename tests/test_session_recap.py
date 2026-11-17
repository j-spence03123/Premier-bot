from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from graphics.session_recap import draw_session_recap
from services.matchfeed import next_matchfeed_counts
from services.session_recap import post_session_recaps, session_match
from services.session_recap import prepare_session_recap
from utils.session_summary import session_rr_totals


BASE = datetime(2026, 11, 17, 18, tzinfo=timezone.utc)
PLAYERS = [
    {"puuid": "kevin", "name": "Kevin", "tag": "TEST", "team_id": "Red"},
    {"puuid": "spam", "name": "Spam", "tag": "TEST", "team_id": "Red"},
]


def add_match(feed, mid="one", players=None, started=BASE, won=13, lost=8):
    players = players or PLAYERS
    finished = started + timedelta(minutes=35)
    detail = {
        "metadata": {"map": {"name": "Abyss"}},
        "players": players,
        "teams": [{"team_id": "Red", "rounds": {"won": won, "lost": lost}}],
        "kills": [
            {"round": 10, "time_in_round_in_ms": index * 1000,
             "killer": {"puuid": "spam"}, "victim": {}}
            for index in range(1, 5)
        ],
    }
    record = session_match(detail, players, mid, started, finished, [])
    counts, footer = next_matchfeed_counts(feed, players, mid, started, finished, recap_match=record)
    feed["match_counts"] = counts
    return footer


def active_session(feed):
    return next(iter(feed["match_counts"]["sessions"].values()))


def test_group_and_solo_sessions_are_independent():
    feed = {}
    add_match(feed)
    footer = add_match(feed, "two", started=BASE + timedelta(minutes=45))
    solo = add_match(feed, "three", players=PLAYERS[:1], started=BASE + timedelta(minutes=90))
    assert footer.startswith("Second group")
    assert solo.startswith("First solo")
    assert sorted(s["count"] for s in feed["match_counts"]["sessions"].values()) == [1, 2]


def test_new_session_preserves_unsent_recap_after_one_hour_gap():
    feed = {}
    add_match(feed)
    old = deepcopy(active_session(feed))
    footer = add_match(feed, "two", started=BASE + timedelta(minutes=95))
    assert footer.startswith("First group")
    assert feed["match_counts"]["pending_recaps"][old["recap_id"]] == old


def test_closed_session_is_not_reopened_by_late_completion():
    feed = {}
    add_match(feed)
    active_session(feed)["recap_message_id"] = "123"
    footer = add_match(feed, "two", started=BASE + timedelta(minutes=45))
    assert footer.startswith("First group")
    assert not feed["match_counts"]["pending_recaps"]


def test_legacy_counts_do_not_invent_match_history():
    feed = {}
    add_match(feed)
    session = active_session(feed)
    del session["matches"]
    session["count"] = 10
    add_match(feed, "two", started=BASE + timedelta(minutes=45))
    assert active_session(feed)["count"] == 1


def test_recording_duplicate_match_is_idempotent_and_copy_isolated():
    feed = {}
    add_match(feed)
    original = deepcopy(feed)
    footer = add_match(feed)
    assert active_session(feed)["count"] == 1
    assert footer.startswith("First group")
    assert feed == original


def delivery(feed, previous_messages=()):
    async def history(**kwargs):
        for message in previous_messages:
            yield message
    channel = SimpleNamespace(history=history, send=AsyncMock(return_value=SimpleNamespace(id=99)))
    client = SimpleNamespace(get_channel=lambda _: channel, user=SimpleNamespace(id=7))
    feeds = {"1": feed}
    save = Mock()
    return channel, dict(client=client, feeds=feeds, load_matchfeeds=lambda: deepcopy(feeds),
                         save_matchfeed_progress=save)


@pytest.mark.asyncio
async def test_recap_due_at_one_hour_and_sent_once_after_restart():
    feed = {"channel_id": 1, "started_at": BASE.isoformat()}
    add_match(feed)
    channel, args = delivery(feed)
    await post_session_recaps(**args, now=BASE + timedelta(minutes=94))
    channel.send.assert_not_awaited()
    await post_session_recaps(**args, now=BASE + timedelta(minutes=95))
    channel.send.assert_awaited_once()
    assert active_session(feed)["recap_message_id"] == "99"
    _, restarted = delivery(deepcopy(feed))
    await post_session_recaps(**restarted, now=BASE + timedelta(hours=3))
    restarted["client"].get_channel(1).send.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_discord_post_recovers_without_duplicate():
    feed = {"channel_id": 1, "started_at": BASE.isoformat()}
    add_match(feed)
    message = SimpleNamespace(id=44, author=SimpleNamespace(id=7), attachments=[
        SimpleNamespace(filename=f"session-{active_session(feed)['recap_id']}.png")
    ])
    channel, args = delivery(feed, [message])
    await post_session_recaps(**args, now=BASE + timedelta(hours=2))
    channel.send.assert_not_awaited()
    assert active_session(feed)["recap_message_id"] == "44"


@pytest.mark.asyncio
async def test_failed_post_can_be_retried():
    feed = {"channel_id": 1, "started_at": BASE.isoformat()}
    add_match(feed)
    channel, args = delivery(feed)
    channel.send.side_effect = RuntimeError("temporarily unavailable")
    await post_session_recaps(**args, now=BASE + timedelta(hours=2))
    assert not active_session(feed).get("recap_message_id")
    args["save_matchfeed_progress"].assert_not_called()
    channel.send.side_effect = None
    await post_session_recaps(**args, now=BASE + timedelta(hours=2))
    assert active_session(feed)["recap_message_id"] == "99"


@pytest.mark.asyncio
async def test_disabled_feed_does_not_post():
    feed = {"channel_id": 1, "started_at": BASE.isoformat()}
    add_match(feed)
    channel, args = delivery(feed)
    args["load_matchfeeds"] = lambda: {}
    await post_session_recaps(**args, now=BASE + timedelta(hours=2))
    channel.send.assert_not_awaited()


def test_session_card_renders_results_and_highlights():
    feed = {}
    add_match(feed)
    add_match(feed, "two", started=BASE + timedelta(minutes=45), won=7, lost=13)
    with Image.open(BytesIO(draw_session_recap(active_session(feed)).getvalue())) as image:
        assert image.width == 1200
        assert image.height >= 500


def test_rr_totals_include_losses_and_require_every_match():
    feed = {}
    add_match(feed)
    add_match(feed, "two", started=BASE + timedelta(minutes=45))
    session = active_session(feed)
    for match, values in zip(session["matches"], ((20, -18), (-10, None))):
        for entry, change in zip(match["rr_changes"], values):
            entry["change"] = change
    totals = session_rr_totals(session)
    assert totals[0]["rr"] == 10
    assert totals[1]["rr"] is None
    assert totals[1]["covered_games"] == 1
    session["matches"][1]["rr_changes"][1]["change"] = 0
    assert session_rr_totals(session)[1]["rr"] == -18


@pytest.mark.asyncio
async def test_missing_rr_is_refreshed_by_match_id_before_summary(monkeypatch):
    from services import session_recap
    monkeypatch.setattr(session_recap.asyncio, "sleep", AsyncMock())
    summary = AsyncMock(return_value="A strong session.")
    monkeypatch.setattr(session_recap, "generate_session_summary", summary)
    feed = {}
    add_match(feed, players=PLAYERS[:1])
    session = active_session(feed)
    api = AsyncMock(return_value=[
        {"match_id": "unrelated", "mmr_change_to_last_game": 99},
        {"match_id": "one", "mmr_change_to_last_game": 24},
    ])
    result = await prepare_session_recap(
        session, "kind", accounts={"1": {"name": "Kevin", "tag": "TEST"}},
        cached_api=api, affinity="eu", http_session=object(), api_key="test", model="test",
    )
    assert result == "A strong session."
    assert session_rr_totals(session)[0]["rr"] == 24
    summary.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("history_failed", [False, True])
async def test_poller_only_closes_sessions_after_successful_history_check(monkeypatch, history_failed):
    from services import background_tasks

    monkeypatch.setattr(background_tasks.asyncio, "sleep", AsyncMock())
    post = AsyncMock()
    monkeypatch.setattr(background_tasks, "post_session_recaps", post)
    client = Mock(wait_until_ready=AsyncMock(), is_closed=Mock(side_effect=[False, True]))
    async def api(path, *args, **kwargs):
        if "stored-matches" in path:
            if history_failed:
                raise RuntimeError("History unavailable")
            return []
        return {"current": {"tier": {"id": 18, "name": "Diamond 1"}}}
    feeds = {"1": {"channel_id": 1}}
    await background_tasks.matchfeed_loop(
        client=client, load_matchfeeds=lambda: feeds,
        load_accounts=lambda: {"1": {"name": "Kevin", "tag": "TEST"}},
        load_rank_states=lambda: {}, save_rank_states=Mock(), cached_api=api,
        cached=AsyncMock(), match_detail=AsyncMock(), parse_time=Mock(),
        play_match_image=AsyncMock(), rank_change_image=AsyncMock(),
        save_matchfeed_progress=Mock(), AFFINITY="eu",
    )
    assert post.await_count == (0 if history_failed else 1)
