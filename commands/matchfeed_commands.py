"""Play-session and automatic matchfeed command implementations."""

from datetime import datetime, timezone
import re

import discord
from discord import app_commands

from utils.recap_tones import TONE_LABELS, normalize_tone


async def play_cmd(interaction: discord.Interaction, action: app_commands.Choice[str], players: str = "", *, load_accounts, load_play_sessions, save_play_sessions):
    key = str(interaction.channel_id)
    sessions = load_play_sessions()
    if action.value == "stop":
        existing = sessions.get(key)
        if not existing:
            return await interaction.response.send_message("There is no active play session in this channel.", ephemeral=True)
        sessions.pop(key, None)
        save_play_sessions(sessions)
        return await interaction.response.send_message("Play session stopped.")

    accounts = load_accounts()
    ids = [str(interaction.user.id)]
    ids.extend(re.findall(r"<@!?(\d+)>|\b(\d{15,20})\b", players))
    ids = list(dict.fromkeys(uid for item in ids for uid in (item if isinstance(item, tuple) else (item,)) if uid))
    missing = [uid for uid in ids if uid not in accounts]
    if missing:
        mentions = ", ".join(f"<@{uid}>" for uid in missing)
        return await interaction.response.send_message(f"Link an account with /register first for: {mentions}", ephemeral=True,
                                                       allowed_mentions=discord.AllowedMentions.none())
    sessions[key] = {"channel_id": interaction.channel_id, "guild_id": interaction.guild_id,
                     "owner_id": interaction.user.id, "players": ids, "seen": [],
                     "started_at": datetime.now(timezone.utc).isoformat()}
    save_play_sessions(sessions)
    tags = " ".join(f"<@{uid}>" for uid in ids)
    await interaction.response.send_message(f"Play session started for {tags}. I’ll check for completed competitive matches every 5 minutes.",
                                            allowed_mentions=discord.AllowedMentions.none())


async def matchfeed_cmd(interaction: discord.Interaction, channel: discord.TextChannel = None, *, load_matchfeeds, save_matchfeeds):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message("Only server administrators can configure the match feed.", ephemeral=True)
    feeds = load_matchfeeds()
    guild_key = str(interaction.guild_id)
    existing = feeds.get(guild_key) or {}
    if channel is None:
        feeds.pop(guild_key, None)
        save_matchfeeds(feeds)
        return await interaction.response.send_message("Automatic match reports disabled for this server.", ephemeral=True)
    if int(existing.get("channel_id", 0)) != channel.id:
        feeds[guild_key] = {
            "channel_id": channel.id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "seen": [],
            "tone": normalize_tone(existing.get("tone")),
        }
    else:
        existing["channel_id"] = channel.id
        existing.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        existing.setdefault("seen", [])
        feeds[guild_key] = existing
    save_matchfeeds(feeds)
    await interaction.response.send_message(
        f"Automatic match reports will post in {channel.mention} for each new competitive match involving a registered account. Same-team players are combined into one post, and rank changes are announced there too.",
        ephemeral=True,
    )


async def matchfeed_tone_cmd(interaction: discord.Interaction, tone: app_commands.Choice[str], *, load_matchfeeds, save_matchfeeds):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message("Only server administrators can configure the match feed.", ephemeral=True)
    feeds = load_matchfeeds()
    feed = feeds.get(str(interaction.guild_id))
    if not feed:
        return await interaction.response.send_message("Set up a match feed with /matchfeed first.", ephemeral=True)
    if tone.value not in TONE_LABELS:
        return await interaction.response.send_message("Unknown recap tone.", ephemeral=True)
    feed["tone"] = tone.value
    save_matchfeeds(feeds)
    await interaction.response.send_message(f"Matchfeed recap tone set to **{TONE_LABELS[tone.value]}**.", ephemeral=True)
