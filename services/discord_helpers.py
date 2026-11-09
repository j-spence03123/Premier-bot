"""Feature helpers with explicitly supplied application dependencies."""
import discord

async def discord_display_name(guild, user_id, *, client):
    member = guild.get_member(user_id) if guild else None
    member = member or client.get_user(user_id)
    if member:
        return member.display_name
    if guild:
        try:
            return (await guild.fetch_member(user_id)).display_name
        except discord.DiscordException:
            pass
    return 'Former server member'

async def build_lineup_reminder(title, intro, guild=None, *, current_week, discord_display_name, fmt_range, lineup_card_file, load_agents, matching_map_key):
    embed = discord.Embed(title=title, description=intro, colour=16729685)
    week = current_week()
    if not week:
        embed.add_field(name='Lineup', value='No current map is available in season.json.', inline=False)
        return (embed, [], None)
    map_name = week['map']
    data = load_agents()
    picks = data.get(matching_map_key(data, map_name), {})
    picked_user_ids = []
    lines = []
    slots = []
    for user_id, agent in sorted(picks.items(), key=lambda item: str(item[0])):
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            continue
        picked_user_ids.append(uid)
        player_name = await discord_display_name(guild, uid)
        slots.append({'player': player_name, 'agent': agent, 'riot': ''})
        lines.append(f'<@{uid}> — **{agent}**')
    picked_count = len(slots)
    while len(slots) < 5:
        slots.append({'player': 'Open slot', 'agent': None, 'riot': 'Waiting for an agent pick'})
    if not lines:
        lines = ['Nobody has selected an agent yet. Use /agent to add a pick.']
    embed.add_field(name=f'{map_name} lineup', value='\n'.join(lines)[:1024], inline=False)
    missing = max(0, 5 - picked_count)
    embed.set_footer(text=f'{picked_count}/5 agent picks · {missing} missing')
    week_label = f"{week['label']} · {fmt_range(week['start'], week['end'])}"
    lineup_file = await lineup_card_file(map_name, week_label, slots)
    embed.set_image(url='attachment://lineup.png')
    return (embed, picked_user_ids, lineup_file)
