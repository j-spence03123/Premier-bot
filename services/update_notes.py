"""Post hand-written update notes from UPDATES.md to each match feed channel once."""

import logging
import re

import discord

logger = logging.getLogger(__name__)

DISCORD_LIMIT = 2000
_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def parse_update_notes(text):
    """Return ``[{"id", "body"}]`` for each ``## heading`` section, in file order (newest first)."""
    text = _COMMENT.sub("", text)
    headings = list(_HEADING.finditer(text))
    notes = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[heading.end():end].strip()
        if body:
            notes.append({"id": heading.group(1), "body": body})
    return notes


def pending_update_notes(notes, announced):
    """Return ``(notes to post oldest first, state to save)``.

    The first run has no saved state, so it posts only the newest note instead of the whole history.
    """
    if "announced" not in announced:
        return notes[:1], {"announced": [note["id"] for note in notes]}
    seen = set(announced["announced"])
    new = [note for note in notes if note["id"] not in seen]
    return list(reversed(new)), {"announced": announced["announced"] + [note["id"] for note in reversed(new)]}


def format_update_message(notes):
    if len(notes) == 1:
        message = f"**New update**\n{notes[0]['body']}"
    else:
        message = "**New updates**\n" + "\n\n".join(f"**{note['id']}**\n{note['body']}" for note in notes)
    if len(message) > DISCORD_LIMIT:
        message = message[:DISCORD_LIMIT - 1].rstrip() + "…"
    return message


async def announce_update_notes(*, client, notes_path, load_matchfeeds, load_announced, save_announced):
    """Post new notes to every match feed channel; remember them unless every post failed."""
    try:
        notes = parse_update_notes(notes_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"Could not read update notes from {notes_path}: {exc}")
        return
    try:
        to_post, state = pending_update_notes(notes, load_announced())
        feeds = load_matchfeeds()
    except Exception as exc:
        logger.warning(f"Update notes state is unavailable: {exc}")
        return
    if to_post:
        message = format_update_message(to_post)
        posted = failed = 0
        for guild_key, feed in feeds.items():
            try:
                channel_id = int(feed["channel_id"])
                channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
                await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
                posted += 1
            except (KeyError, TypeError, ValueError, discord.HTTPException) as exc:
                logger.warning(f"Could not post update notes in guild {guild_key}: {exc}")
                failed += 1
        if failed and not posted:
            return  # try again on the next start
        logger.info(f"Posted {len(to_post)} update note(s) to {posted} match feed channel(s)")
    try:
        save_announced(state)
    except Exception as exc:
        logger.warning(f"Could not save announced update notes: {exc}")
