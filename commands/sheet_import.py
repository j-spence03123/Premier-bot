"""Discord commands for importing lineups and playbooks from separate sheets."""

import asyncio
import re

import discord

from services.agent_helpers import find_lineup_week, week_pick_key
from services.google_sheet_import import (
    DocImportError, PLAYBOOK_TEMPLATE, parse_lineup_sheet, parse_playbook_sheet,
)
from services.json_store import JsonStoreError


DISCORD_ID = re.compile(r"(?:<@!?(\d{15,20})>|(\d{15,20}))")
AGENT_ALIASES = {"brim": "brimstone", "kj": "killjoy"}


async def _resolve_player(player, guild, accounts):
    match = DISCORD_ID.fullmatch(player)
    name = player.lstrip("@").casefold()
    linked = [uid for uid, account in accounts.items()
              if name in {str(account.get("name", "")).casefold(),
                          f"{account.get('name', '')}#{account.get('tag', '')}".casefold()}]
    if match:
        uid = int(match[1] or match[2])
    elif "#" in name and len(linked) == 1:
        uid = int(linked[0])
    else:
        try:
            members = await guild.query_members(query=player.lstrip("@"), limit=100)
        except (asyncio.TimeoutError, discord.DiscordException, ValueError):
            members = guild.members
        exact = {member.id for member in members
                 if name in {member.name.casefold(), member.display_name.casefold()}}
        if len(exact) == 1:
            return str(exact.pop())
        if len(exact) > 1 or len(linked) > 1:
            raise DocImportError(f"'{player}' matches multiple players. Use their Discord user ID in column B.")
        if not linked:
            raise DocImportError(f"Couldn't find '{player}'. Use a Discord name, Discord user ID, or linked Riot ID in column B.")
        uid = int(linked[0])
    if guild.get_member(uid) is None:
        try:
            await guild.fetch_member(uid)
        except discord.NotFound as exc:
            raise DocImportError(f"'{player}' is not a member of this server.") from exc
        except discord.HTTPException as exc:
            raise DocImportError("Couldn't verify the lineup players with Discord. Try again.") from exc
    return str(uid)


async def _lineup_picks(rows, guild, runtime):
    accounts = runtime.load_accounts()
    agent_names = {name.casefold(): name for name in await runtime.agent_names()}
    picks = {}
    for player, agent in rows:
        canonical_agent = agent_names.get(AGENT_ALIASES.get(agent.casefold(), agent.casefold()))
        if not canonical_agent:
            raise DocImportError(f"'{agent}' isn't a known VALORANT agent.")
        user_id = await _resolve_player(player, guild, accounts)
        if user_id in picks or canonical_agent in picks.values():
            raise DocImportError("The lineup has a duplicate player or agent.")
        picks[user_id] = canonical_agent
    return picks


async def import_lineup(interaction, sheet, label, runtime):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message("Only server administrators can import lineups.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        week = find_lineup_week(runtime.load_season(), label=label.strip())
        if not label.strip() or not week:
            raise DocImportError("Use the week label or start date shown in /schedule.")
        rows = parse_lineup_sheet(await runtime.read_google_sheet(sheet), week["map"])
        picks = await _lineup_picks(rows, interaction.guild, runtime)
        agents = runtime.load_agents()
        agents[week_pick_key(week, interaction.guild.id)] = picks
        runtime.save_agents(agents)
    except (DocImportError, JsonStoreError) as exc:
        return await interaction.followup.send(f"Lineup import stopped. {exc}"[:1900], ephemeral=True,
                                               allowed_mentions=discord.AllowedMentions.none())
    await interaction.followup.send(
        f"Saved {len(picks)} picks for {week['label']} on {week['map']}. Open them with /lineup week:{week['label']}.",
        ephemeral=True,
    )


async def import_playbook(interaction, sheet, runtime):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message("Only server administrators can import playbooks.", ephemeral=True)
    if not sheet.strip():
        return await interaction.response.send_message(
            "Paste this template into cell A1 of a playbook tab, then use /importplaybook with its sharing link.\n"
            f"```text\n{PLAYBOOK_TEMPLATE}\n```",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=True)
    try:
        strategies = parse_playbook_sheet(await runtime.read_google_sheet(sheet))
        maps = await runtime.available_playbook_maps()
        for draft in strategies:
            map_name = runtime.find_playbook_map(maps, draft["map"])
            if not map_name:
                raise DocImportError(f"'{draft['map']}' isn't a map in /playbook.")
            draft["map"] = map_name
        added, skipped = runtime.playbook_service.import_strategies(strategies)
    except (DocImportError, JsonStoreError) as exc:
        return await interaction.followup.send(f"Playbook import stopped. {exc}"[:1900], ephemeral=True,
                                               allowed_mentions=discord.AllowedMentions.none())
    await interaction.followup.send(f"Added {added} strategies. Skipped {skipped} identical entries.", ephemeral=True)
