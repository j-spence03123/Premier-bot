"""Collect verified session highlights and deliver idle-session recap cards."""

import logging
import asyncio
from datetime import datetime, timezone

import discord

from graphics.session_recap import draw_session_recap
from services.account_registry import iter_linked_accounts
from services.ai_recap import recap_facts, _featured_rounds, generate_session_summary, recap_with_deadline
from services.matchfeed import SESSION_IDLE_LIMIT
from utils.formatting import parse_time
from urllib.parse import quote

logger = logging.getLogger(__name__)


def session_match(detail, players, match_id, started, finished, context, rank_histories=None, *, facts=None):
    if facts is None:
        facts = recap_facts(detail, players, players[0], registered_only=True)
    rounds = facts["rounds"] or {}
    won, lost = rounds.get("won", 0), rounds.get("lost", 0)
    moments = []
    for item in _featured_rounds(facts["round_highlights"]):
        multi = item.get("multikills")
        if multi:
            play = max(multi, key=lambda play: play["kills"])
            text = f"{play['player']} found {play['kills']} kills in round {item['round']}."
            priority = play["kills"] * 10
        else:
            opening = item.get("first_blood") or item["first_death"]
            action = "landed first blood" if item.get("first_blood") else "was first down"
            text = f"{opening['player']} {action} {opening['seconds']:g} seconds into round {item['round']}."
            priority = 2 if item.get("first_blood") else 1
        moments.append({"text": text, "priority": priority})
    rank_changes = []
    rr_changes = []
    for player in players:
        key = f"{player.get('name', '')}#{player.get('tag', '')}".casefold()
        change = next((row.get("mmr_change_to_last_game") for row in (rank_histories or {}).get(key, [])
                       if str(row.get("match_id")) == str(match_id)), None)
        rr_changes.append({
            "player_id": player.get("puuid") or key, "player": player["name"],
            "account_key": key, "change": change if type(change) is int else None,
        })
    for player in context:
        for change in player.get("rank_changes", []):
            if change["when"] == "this match":
                rank_changes.append(f"{player['player']} ranked {change['direction']} to {change['to_rank']}.")
    return {
        "id": str(match_id), "started": started.isoformat(), "finished": finished.isoformat(),
        "map": facts["map"] or "Unknown map",
        "result": "W" if won > lost else "L" if won < lost else "D",
        "score": f"{won}–{lost}", "margin": won - lost,
        "moments": moments, "rank_changes": rank_changes, "rr_changes": rr_changes,
        "smurfs": [player for player in facts["teammates"] if player.get("is_smurf")],
    }


async def prepare_session_recap(session, tone, *, accounts, cached_api, affinity, http_session, api_key, model):
    """Retry rank history that had not arrived when individual matches were posted."""
    missing = {entry["account_key"] for match in session["matches"] for entry in match.get("rr_changes", [])
               if entry.get("change") is None}
    linked = {f"{account['name']}#{account['tag']}".casefold(): account
              for _, account, _ in iter_linked_accounts(accounts)}
    for key in sorted(missing):
        account = linked.get(key)
        if not account:
            continue
        try:
            await asyncio.sleep(2.3)
            region = account.get("region") or affinity
            history = await cached_api(
                f"/valorant/v1/mmr-history/{region}/{quote(account['name'])}/{quote(account['tag'])}", 100,
            )
            changes = {str(row.get("match_id")): row.get("mmr_change_to_last_game")
                       for row in history if isinstance(row, dict)}
            for match in session["matches"]:
                change = changes.get(match["id"])
                for entry in match.get("rr_changes", []):
                    if entry["account_key"] == key and type(change) is int:
                        entry["change"] = change
        except Exception as exc:
            logger.warning(f"Session RR history unavailable for {key}: {exc}")
    return await recap_with_deadline(generate_session_summary(http_session, api_key, model, session, tone))


async def post_session_recaps(*, client, feeds, load_matchfeeds, save_matchfeed_progress, now=None, prepare_recap=None):
    now = now or datetime.now(timezone.utc)
    for guild_key, feed in feeds.items():
        counts = feed.get("match_counts") or {}
        sessions = list(counts.get("pending_recaps", {}).values()) + list(counts.get("sessions", {}).values())
        for session in sessions:
            last_finished = parse_time(session.get("last_finished"))
            if (not session.get("matches") or session.get("recap_message_id") or not last_finished
                    or now < last_finished + SESSION_IDLE_LIMIT):
                continue
            current = load_matchfeeds().get(guild_key)
            if not current or (current.get("channel_id"), current.get("started_at")) != (
                    feed.get("channel_id"), feed.get("started_at")):
                break
            try:
                channel = client.get_channel(int(feed["channel_id"])) or await client.fetch_channel(int(feed["channel_id"]))
                filename = f"session-{session['recap_id']}.png"
                # Recover from a restart between Discord accepting a post and saving its ID.
                sent = None
                try:
                    async for message in channel.history(limit=100, after=last_finished):
                        if message.author.id == client.user.id and any(a.filename == filename for a in message.attachments):
                            sent = message
                            break
                except discord.Forbidden:
                    logger.warning(f"Cannot check recent messages for duplicate session recaps in guild {guild_key}")
                if sent is None:
                    if prepare_recap and not session.get("summary"):
                        try:
                            session["summary"] = await prepare_recap(session, feed.get("tone"))
                        except Exception as exc:
                            logger.warning(f"Session summary unavailable for guild {guild_key}: {exc}")
                    buffer = await asyncio.to_thread(draw_session_recap, session)
                    sent = await channel.send(
                        file=discord.File(buffer, filename=filename),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                session["recap_message_id"] = str(sent.id)
                counts.get("pending_recaps", {}).pop(session["recap_id"], None)
                save_matchfeed_progress(feeds, guild_key)
            except Exception as exc:
                logger.exception(f"Session recap failed for guild {guild_key}: {exc}")
