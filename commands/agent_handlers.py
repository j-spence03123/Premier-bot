"""Feature command implementations; application dependencies are injected at registration."""
from __future__ import annotations
import discord

async def agent_cmd(interaction, agent_name, map_name='', *, NO_MAP, agent_names, assign_agent, resolve_map):
    agent = next((n for n in await agent_names() if n.lower() == agent_name.strip().lower()), None)
    if not agent:
        return await interaction.response.send_message(f"I don't know an agent called {agent_name}. Start typing to see the list.", ephemeral=True)
    picked_map = resolve_map(map_name)
    if not picked_map:
        return await interaction.response.send_message(NO_MAP, ephemeral=True)
    conflict, count = assign_agent(picked_map, interaction.user.id, agent)
    if conflict:
        return await interaction.response.send_message(conflict, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message(f'{interaction.user.mention} will play **{agent}** on **{picked_map}**. ({count} picked, /lineup to see everyone)', allowed_mentions=discord.AllowedMentions.none())

async def assignagent(interaction, user, agent_name, map_name='', *, NO_MAP, agent_names, assign_agent, resolve_map):
    if not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can use this command.', ephemeral=True)
    agent = next((n for n in await agent_names() if n.lower() == agent_name.strip().lower()), None)
    if not agent:
        return await interaction.response.send_message(f"I don't know an agent called {agent_name}. Start typing to see the list.", ephemeral=True)
    picked_map = resolve_map(map_name)
    if not picked_map:
        return await interaction.response.send_message(NO_MAP, ephemeral=True)
    conflict, count = assign_agent(picked_map, user.id, agent)
    if conflict:
        return await interaction.response.send_message(conflict, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message(f'Assigned **{agent}** to {user.mention} on **{picked_map}**. ({count} picked, /lineup to see everyone)', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

async def lineup(interaction, map_name='', *, NO_MAP, discord_display_name, fmt_range, lineup_card_file, load_agents, load_season, matching_map_key, resolve_map):
    picked_map = resolve_map(map_name)
    if not picked_map:
        return await interaction.response.send_message(NO_MAP, ephemeral=True)
    if not interaction.response.is_done():
        await interaction.response.defer()
    agent_data = load_agents()
    picks = agent_data.get(matching_map_key(agent_data, picked_map), {})
    week = next((w for w in (load_season() or {}).get('weeks', []) if w['map'].casefold() == picked_map.casefold()), None)
    week_label = f"{week['label']} · {fmt_range(week['start'], week['end'])}" if week else 'Premier lineup'
    slots = []
    lines = []
    for uid, agent in sorted(picks.items(), key=lambda item: str(item[0])):
        try:
            numeric_uid = int(uid)
        except (TypeError, ValueError):
            continue
        player_name = await discord_display_name(interaction.guild, numeric_uid)
        slots.append({'player': player_name, 'agent': agent, 'riot': ''})
        lines.append(f'<@{uid}> · **{agent}**')
    picked_count = len(slots)
    while len(slots) < 5:
        slots.append({'player': 'Open slot', 'agent': None, 'riot': 'Waiting for an agent pick'})
    if not lines:
        lines = ['No agent picks yet. Use /agent to claim a pick.']
    elif picked_count < 5:
        lines.append(f'**{5 - picked_count} pick(s) still open** · use /agent to fill them.')
    lineup_file = await lineup_card_file(picked_map, week_label, slots)
    embed = discord.Embed(title=f'Lineup · {picked_map}', description=f'{week_label}\n\n' + '\n'.join(lines), colour=16729685)
    embed.set_image(url='attachment://lineup.png')
    embed.set_footer(text=f'{picked_count}/5 agent picks · Use /agent to pick or change your agent')
    await interaction.followup.send(embed=embed, file=lineup_file, allowed_mentions=discord.AllowedMentions.none())

async def clearagent(interaction, map_name='', *, NO_MAP, load_agents, resolve_map, save_agents):
    picked_map = resolve_map(map_name)
    if not picked_map:
        return await interaction.response.send_message(NO_MAP, ephemeral=True)
    data = load_agents()
    if data.get(picked_map, {}).pop(str(interaction.user.id), None) is None:
        return await interaction.response.send_message(f"You hadn't picked an agent for {picked_map}.", ephemeral=True)
    save_agents(data)
    await interaction.response.send_message(f'Cleared your pick for {picked_map}.', ephemeral=True)
