"""Import Premier plans from a Google Doc."""

import re

import discord

from services.agent_helpers import find_lineup_week, week_pick_key
from services.google_doc_import import DocImportError, TEMPLATE, parse_import_document
from services.json_store import JsonStoreError


DISCORD_ID = re.compile(r"(?:<@!?(\d{15,20})>|(\d{15,20}))")


async def _lineup_updates(lineups, guild, runtime):
    season = runtime.load_season()
    accounts = runtime.load_accounts()
    players = {f"{account['name']}#{account['tag']}".casefold(): uid
               for uid, account in accounts.items() if account.get("name") and account.get("tag")}
    agent_names = {name.casefold(): name for name in await runtime.agent_names()}
    checked_members = set()
    updates = {}
    for label, rows in lineups:
        week = find_lineup_week(season, label=label)
        if not week:
            raise DocImportError(f"'{label}' is not in /schedule. Use the week label or start date.")
        key = week_pick_key(week, guild.id)
        if key in updates:
            raise DocImportError(f"{week['label']} appears more than once. Use one lineup section per week.")
        if not 1 <= len(rows) <= 5:
            raise DocImportError(f"{week['label']} needs between one and five player picks.")
        picks = {}
        for player, agent in rows:
            match = DISCORD_ID.fullmatch(player)
            user_id = next(group for group in match.groups() if group) if match else players.get(player.casefold())
            if not user_id:
                raise DocImportError(f"Couldn't find '{player}'. Use a linked Riot ID (Name#Tag) or a Discord user ID.")
            uid = int(user_id)
            if uid not in checked_members and guild.get_member(uid) is None:
                try:
                    await guild.fetch_member(uid)
                except discord.NotFound as exc:
                    raise DocImportError(f"'{player}' is not a member of this server.") from exc
                except discord.HTTPException as exc:
                    raise DocImportError("Couldn't verify the lineup players with Discord. Try again.") from exc
            checked_members.add(uid)
            canonical_agent = agent_names.get(agent.casefold())
            if not canonical_agent:
                raise DocImportError(f"'{agent}' isn't a known VALORANT agent.")
            if user_id in picks or canonical_agent in picks.values():
                raise DocImportError(f"{week['label']} has a duplicate player or agent.")
            picks[user_id] = canonical_agent
        updates[key] = picks
    return updates


async def import_doc(interaction, document, runtime):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message("Only server administrators can import a document.", ephemeral=True)
    if not document.strip():
        return await interaction.response.send_message(
            "Paste a Google Docs link into /importdoc. Use a document anyone with the link can view. "
            "You can include just lineups, just playbooks, or both. Each lineup sets the picks for that week.\n"
            f"```text\n{TEMPLATE}\n```",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=True)
    added = skipped = 0
    try:
        text = await runtime.read_google_doc(document)
        lineups, strategies = parse_import_document(text)
        updates = await _lineup_updates(lineups, interaction.guild, runtime) if lineups else {}
        if strategies:
            maps = await runtime.available_playbook_maps()
            for draft in strategies:
                map_name = runtime.find_playbook_map(maps, draft["map"])
                if not map_name:
                    raise DocImportError(f"'{draft['map']}' isn't a map in /playbook.")
                draft["map"] = map_name
        agents = runtime.load_agents() if updates else None
        if strategies:
            added, skipped = runtime.playbook_service.import_strategies(strategies)
        if updates:
            agents.update(updates)
            runtime.save_agents(agents)
    except (DocImportError, JsonStoreError) as exc:
        message = f"Import stopped. {exc}"
        if added:
            message += f" Saved {added} playbook strategies. You can retry the same document to save the lineups."
        return await interaction.followup.send(message[:1900], ephemeral=True,
                                               allowed_mentions=discord.AllowedMentions.none())

    parts = []
    if updates:
        parts.append(f"Saved {len(updates)} weekly lineup(s). Choose a week in /lineup to view one.")
    if strategies:
        parts.append(f"Added {added} playbook strategy/strategies. {skipped} already existed.")
    await interaction.followup.send(" ".join(parts), ephemeral=True)
