"""Feature helpers with explicitly supplied application dependencies."""
import asyncio
import hashlib

async def icon_maps(*, cached, client):
    """Agent image URLs and rank tier icons from valorant-api.com, cached a week."""

    async def fetch():

        async def get_json(url):
            async with client.http_session.get(url) as r:
                r.raise_for_status()
                return await r.json()
        agents_data, tiers_data = await asyncio.gather(get_json('https://valorant-api.com/v1/agents?isPlayableCharacter=true'), get_json('https://valorant-api.com/v1/competitivetiers'))
        agents, tiers = (agents_data['data'], tiers_data['data'])
        return {'agents': {a['uuid'].lower(): a.get('displayIcon') or a.get('bustPortrait') or a.get('killfeedPortrait') or a.get('fullPortrait') for a in agents}, 'agent_icon_urls': {a['uuid'].lower(): list(dict.fromkeys((url for url in (a.get('displayIcon'), a.get('bustPortrait'), a.get('killfeedPortrait'), a.get('fullPortrait')) if url))) for a in agents}, 'agent_names': {a['uuid'].lower(): a['displayName'] for a in agents}, 'tiers': {str(t['tier']): t.get('smallIcon') for t in tiers[-1]['tiers']}}
    try:
        return await cached('icons:maps5', 7 * 86400, fetch)
    except Exception:
        return await cached('icons:maps2', None, fetch)

async def icon_img(url, size, *, ICON_DIR, _icon_locks, client, load_icon_image):
    if not url:
        return None
    path = ICON_DIR / (hashlib.md5(url.encode()).hexdigest() + '.png')
    try:
        lock = _icon_locks.setdefault(url, asyncio.Lock())
        async with lock:
            if not path.exists():
                async with client.http_session.get(url) as r:
                    if r.status != 200:
                        return None
                    path.write_bytes(await r.read())
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, load_icon_image, path, size)
    except Exception:
        return None

async def valorant_map_catalog(*, cached, client):

    async def fetch():
        async with client.http_session.get('https://valorant-api.com/v1/maps') as response:
            response.raise_for_status()
            return (await response.json()).get('data', [])
    return await cached('valorant:map-catalog', 7 * 86400, fetch)

async def map_background_path(map_uuid, map_name='Unknown', *, ICON_DIR, client):
    """Fetch map splash art into the same cache path used by match-feed cards."""
    path = ICON_DIR / f'map_{map_uuid}.jpg'
    if path.exists():
        return path
    try:
        async with client.http_session.get(f'https://valorant-api.com/v1/maps/{map_uuid}') as response:
            response.raise_for_status()
            map_info = (await response.json()).get('data', {})
        image_url = map_info.get('splash') or map_info.get('listViewIcon')
        if image_url:
            async with client.http_session.get(image_url) as response:
                response.raise_for_status()
                path.write_bytes(await response.read())
    except Exception as exc:
        print(f'Map art unavailable for {map_name}: {exc}')
        return None
    return path if path.exists() else None
