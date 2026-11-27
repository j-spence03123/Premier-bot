from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from services.update_notes import (DISCORD_LIMIT, announce_update_notes, format_update_message,
                                   parse_update_notes, pending_update_notes)

NOTES = """# Bot updates

<!--
## not-a-note
Instructions in comments are ignored.
-->

## 2026-11-29
Third change.

## 2026-11-28
Second change.

## 2026-11-27
First change.
"""


def test_parse_reads_sections_newest_first_and_skips_comments():
    notes = parse_update_notes(NOTES)
    assert [note["id"] for note in notes] == ["2026-11-29", "2026-11-28", "2026-11-27"]
    assert notes[2]["body"] == "First change."


def test_first_run_posts_only_the_newest_note_and_remembers_all():
    to_post, state = pending_update_notes(parse_update_notes(NOTES), {})
    assert [note["id"] for note in to_post] == ["2026-11-29"]
    assert set(state["announced"]) == {"2026-11-27", "2026-11-28", "2026-11-29"}


def test_later_runs_post_new_notes_oldest_first():
    notes = parse_update_notes(NOTES)
    to_post, state = pending_update_notes(notes, {"announced": ["2026-11-27"]})
    assert [note["id"] for note in to_post] == ["2026-11-28", "2026-11-29"]
    assert pending_update_notes(notes, state)[0] == []


def test_message_formats_one_or_many_notes_within_discord_limit():
    one, two = parse_update_notes(NOTES)[:2]
    assert format_update_message([one]) == "**New update**\nThird change."
    assert format_update_message([two, one]).startswith("**New updates**\n**2026-11-28**\nSecond change.")
    long = format_update_message([{"id": "x", "body": "a" * 3000}])
    assert len(long) == DISCORD_LIMIT


def run_announce(tmp_path, announced, channels, *, notes=NOTES):
    path = tmp_path / "UPDATES.md"
    path.write_text(notes, encoding="utf-8")
    saved = Mock()
    client = SimpleNamespace(get_channel=lambda channel_id: channels.get(channel_id), fetch_channel=AsyncMock(
        side_effect=discord.NotFound(Mock(status=404), "missing")))
    feeds = {str(guild): {"channel_id": channel} for guild, channel in enumerate([1, 2, 3])}
    coroutine = announce_update_notes(client=client, notes_path=path, load_matchfeeds=lambda: feeds,
                                      load_announced=lambda: announced, save_announced=saved)
    return coroutine, saved


@pytest.mark.asyncio
async def test_announce_posts_to_every_feed_and_saves(tmp_path):
    channels = {1: Mock(send=AsyncMock()), 2: Mock(send=AsyncMock())}  # channel 3 no longer exists
    coroutine, saved = run_announce(tmp_path, {"announced": ["2026-11-27", "2026-11-28"]}, channels)
    await coroutine
    for channel in channels.values():
        assert channel.send.await_args.args[0] == "**New update**\nThird change."
    assert saved.call_args.args[0]["announced"][-1] == "2026-11-29"


@pytest.mark.asyncio
async def test_announce_retries_next_start_when_every_post_fails(tmp_path):
    coroutine, saved = run_announce(tmp_path, {"announced": []}, {})
    await coroutine
    saved.assert_not_called()


@pytest.mark.asyncio
async def test_missing_notes_file_does_nothing(tmp_path):
    saved = Mock()
    await announce_update_notes(client=None, notes_path=tmp_path / "missing.md", load_matchfeeds=dict,
                                load_announced=dict, save_announced=saved)
    saved.assert_not_called()


def test_repo_update_notes_parse_with_unique_headings():
    notes = parse_update_notes((Path(__file__).resolve().parent.parent / "UPDATES.md").read_text(encoding="utf-8"))
    assert notes, "UPDATES.md should have at least one entry"
    ids = [note["id"] for note in notes]
    assert len(ids) == len(set(ids))
