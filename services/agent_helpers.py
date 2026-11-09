"""Feature helpers with explicitly supplied application dependencies."""
import asyncio
from datetime import datetime
import discord
from datetime import timezone

async def agent_names(*, FALLBACK_AGENTS, icon_maps):
    try:
        maps = await asyncio.wait_for(icon_maps(), timeout=2.5)
        names = sorted(maps.get('agent_names', {}).values())
        if names:
            return names
    except Exception:
        pass
    return FALLBACK_AGENTS

def matching_map_key(data, map_name):
    normalized = map_name.strip().casefold()
    return next((key for key in data if key.strip().casefold() == normalized), map_name)

def assign_agent(map_name, user_id, agent, *, load_agents, matching_map_key, save_agents):
    data = load_agents()
    map_name = matching_map_key(data, map_name)
    picks = data.setdefault(map_name, {})
    user_id = str(user_id)
    for uid, taken in picks.items():
        if uid != user_id and taken.lower() == agent.lower():
            return (f'{agent} is already taken on {map_name} by <@{uid}>. Pick another agent.', len(picks))
    picks[user_id] = agent
    save_agents(data)
    return (None, len(picks))

def current_week(*, load_season):
    season = load_season()
    if not season:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    return next((w for w in season['weeks'] if w['end'] >= today), None)

def resolve_map(text, *, current_week, load_season):
    """Map name from typed text (matched against season.json), or this week's map."""
    season = load_season()
    if text:
        if not season:
            return text.strip().title()
        return next((w['map'] for w in season['weeks'] if w['map'].lower() == text.strip().lower()), None)
    week = current_week()
    return week['map'] if week else None

async def agent_autocomplete(interaction, current, *, agent_names, app_commands):
    return [app_commands.Choice(name=n, value=n) for n in await agent_names() if current.lower() in n.lower()][:25]

async def lineup_card_file(map_name, week_label, slots, *, icon_img, icon_maps, render_lineup_card):
    agent_icons = {}
    try:
        catalog = await icon_maps()
        uuid_by_name = {name.casefold(): uuid for uuid, name in catalog.get('agent_names', {}).items()}
        icon_jobs = {}
        for slot in slots:
            agent = slot.get('agent')
            if not agent:
                continue
            agent_uuid = uuid_by_name.get(agent.casefold())
            url = catalog.get('agents', {}).get(agent_uuid) if agent_uuid else None
            if url and agent.casefold() not in icon_jobs:
                icon_jobs[agent.casefold()] = icon_img(url, 72)
        loaded_icons = await asyncio.gather(*icon_jobs.values()) if icon_jobs else []
        agent_icons = dict(zip(icon_jobs.keys(), loaded_icons))
    except Exception as exc:
        print(f'Lineup agent icons unavailable: {exc}')
    loop = asyncio.get_running_loop()
    buffer = await loop.run_in_executor(None, render_lineup_card, map_name, week_label, slots, agent_icons)
    return discord.File(buffer, filename='lineup.png')
