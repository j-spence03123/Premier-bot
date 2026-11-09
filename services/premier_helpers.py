"""Feature helpers with explicitly supplied application dependencies."""
import asyncio
from datetime import datetime
import discord
from urllib.parse import quote
from datetime import timezone

async def latest_schedule_tweet(*, X_BEARER, X_KEYWORD, X_USERNAME, cached, x_get):
    """Newest recent tweet containing X_KEYWORD, cached for 30 minutes."""
    if not (X_BEARER and X_USERNAME):
        return None

    async def fetch():
        user = await x_get(f'/users/by/username/{X_USERNAME}')
        tweets = await x_get(f"/users/{user['data']['id']}/tweets", max_results=20, exclude='retweets,replies', **{'tweet.fields': 'created_at'})
        return next((t for t in tweets.get('data', []) if X_KEYWORD in t['text'].lower()), None)
    return await cached('x:latest', 1800, fetch)

def ts(d, style='F', *, parse_time):
    if isinstance(d, str):
        d = parse_time(d)
    return f'<t:{int(d.timestamp())}:{style}>' if d else 'unknown'

def player_table(rows):
    lines = ['Player        Agent     K/D/A     ACS ADR  HS%']
    for r in rows:
        lines.append(f"{r['name'][:12]:<13} {r['agent'][:9]:<9} {r['k']}/{r['d']}/{r['a']:<6} {r['acs']:<3} {r['adr']:<4} {r['hs']}%")
    return '```\n' + '\n'.join(lines) + '\n```'

async def current_rank(name, tag, *, AFFINITY, cached_api):
    """Player's current rank from the v3 MMR endpoint (cached 6 hours)."""
    if not name or not tag:
        return None
    try:
        data = await cached_api(f'/valorant/v3/mmr/{AFFINITY}/pc/{quote(name)}/{quote(tag)}', 6 * 3600)
    except Exception:
        return None
    cur = data.get('current') or {} if isinstance(data, dict) else {}
    tier = cur.get('tier') or {}
    return (tier.get('id') or 0, tier.get('name') or 'Unrated')

async def render_scoreboard(s, filename, *, current_rank, draw_scoreboard, icon_img, icon_maps):
    s = {**s, 'rows': [dict(r) for r in s['rows']], 'enemy_rows': [dict(r) for r in s['enemy_rows']]}
    rows = s['rows'] + s['enemy_rows']
    ranks = await asyncio.gather(*(current_rank(r.get('name'), r.get('tag')) for r in rows))
    for r, rank in zip(rows, ranks):
        if rank:
            r['tier'], r['tier_name'] = rank
    try:
        maps = await icon_maps()
    except Exception:
        maps = {'agents': {}, 'tiers': {}}
    keys, jobs = ([], [])
    for r in rows:
        keys.append(('a', r['agent_id']))
        jobs.append(icon_img(maps['agents'].get(r['agent_id']), 36))
        keys.append(('t', r['tier']))
        jobs.append(icon_img(maps['tiers'].get(str(r['tier'])), 30))
    icons = dict(zip(keys, await asyncio.gather(*jobs)))
    loop = asyncio.get_running_loop()
    image = await loop.run_in_executor(None, draw_scoreboard, s, icons)
    return discord.File(image, filename=filename)

async def load_summaries(matches, *, cached, match_detail, summarise, team_members):
    members = await team_members()

    async def one(m):

        async def build():
            return summarise(await match_detail(m['id']), members)
        try:
            return (m, await cached(f"summary4:{m['id']}", None, build))
        except Exception as e:
            return (m, {'error': str(e)})
    return await asyncio.gather(*(one(m) for m in matches))

def load_season(*, JsonStoreError, SEASON_FILE, read_json):
    try:
        return read_json(SEASON_FILE, None)
    except JsonStoreError as exc:
        print(f'Could not load season configuration: {exc}')
        return None

def season_maps(*, load_season):
    season = load_season()
    return [w['map'] for w in season['weeks'] if 'Playoffs' not in w['map']] if season else []

async def schedule_card_file(season, today, *, map_background_path, render_schedule_card, valorant_map_catalog):
    map_art = {}
    try:
        catalog = await valorant_map_catalog()
        by_name = {str(item.get('displayName', '')).casefold(): item for item in catalog}
        jobs = {}
        for week in season.get('weeks', []):
            map_name = week.get('map', '')
            info = by_name.get(map_name.casefold())
            map_uuid = (info or {}).get('uuid')
            if map_uuid:
                jobs[map_name.casefold()] = map_background_path(map_uuid, map_name)
        paths = await asyncio.gather(*jobs.values()) if jobs else []
        map_art = dict(zip(jobs.keys(), paths))
    except Exception as exc:
        print(f'Schedule map art unavailable: {exc}')
    loop = asyncio.get_running_loop()
    buffer = await loop.run_in_executor(None, render_schedule_card, season, map_art, today)
    return discord.File(buffer, filename='premier-schedule.png')

async def map_autocomplete(interaction, current, *, app_commands, season_maps):
    return [app_commands.Choice(name=m, value=m) for m in season_maps() if current.lower() in m.lower()][:25]

async def valorant_acts(*, cached, client, parse_time):
    """Return VALORANT act seasons from valorant-api.com, newest act first."""

    async def fetch():
        async with client.http_session.get('https://valorant-api.com/v1/seasons') as response:
            response.raise_for_status()
            body = await response.json()
            return body.get('data', [])
    data = await cached('valorant:acts', 86400, fetch)
    now = datetime.now(timezone.utc)
    acts = []
    for item in data:
        if not (item.get('type') or '').casefold().endswith('act'):
            continue
        start = parse_time(item.get('startTime'))
        end = parse_time(item.get('endTime'))
        if not start or not end:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start <= now:
            acts.append({'id': item.get('uuid') or item.get('id'), 'name': item.get('displayName') or item.get('name') or 'VALORANT Act', 'start': start, 'end': end})
    return sorted(acts, key=lambda act: act['start'], reverse=True)
