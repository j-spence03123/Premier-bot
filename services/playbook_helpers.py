"""Feature helpers with explicitly supplied application dependencies."""
from pathlib import Path
import asyncio
import discord
import re

async def available_playbook_maps(*, SETTINGS):
    unique = {}
    for name in SETTINGS.competitive_maps:
        if name:
            unique.setdefault(name.casefold(), name)
    return sorted(unique.values(), key=str.casefold)

def find_playbook_map(maps, map_name, *, playbook_service):
    if not map_name:
        return None
    key = map_name.strip().casefold()
    picked = next((name for name in maps if name.casefold() == key), None)
    if picked:
        return picked
    return next((s['map'] for s in playbook_service.list() if s['map'].casefold() == key), None)

async def playbook_diagram_file(strategy, *, PlaybookDataError, icon_img, playbook_service, render_playbook_card, valorant_map_catalog):
    """Render markers on a local top-down map, or the public map catalog icon."""
    image_asset = (strategy.get('diagram') or {}).get('image_asset')
    if image_asset:
        try:
            image_path = playbook_service.image_path(image_asset)
            if image_path.is_file():
                return discord.File(image_path, filename='playbook-map.' + image_path.suffix.lstrip('.'))
        except (OSError, PlaybookDataError):
            pass
    if not ((strategy.get('diagram') or {}).get('markers') or []):
        return None
    map_name = strategy.get('map', '')
    slug = re.sub('[^a-z0-9]+', '-', map_name.casefold()).strip('-')
    local_path = Path(__file__).resolve().parent / 'assets' / 'playbook_maps' / f'{slug}.png'
    background = local_path if slug and local_path.is_file() else None
    if background is None:
        try:
            catalog = await valorant_map_catalog()
            entry = next((item for item in catalog if str(item.get('displayName', '')).casefold() == map_name.casefold()), {})
            background = await icon_img(entry.get('displayIcon'), 928)
        except Exception as exc:
            print(f'Playbook map image unavailable: {exc}')
    if background is None:
        return None
    loop = asyncio.get_running_loop()
    buffer = await loop.run_in_executor(None, render_playbook_card, map_name, strategy.get('side', ''), strategy.get('name', ''), background, (strategy.get('diagram') or {}).get('markers', []))
    return discord.File(buffer, filename='playbook-map.png') if buffer else None

async def playbook_strategy_file(strategy, page_text, *, playbook_diagram_file, render_strategy_card):
    """Compose strategy text with a local uploaded image or rendered tactical map."""
    diagram_file = await playbook_diagram_file(strategy)
    image_bytes = None
    if diagram_file:
        try:
            image_bytes = await asyncio.to_thread(diagram_file.fp.read)
        finally:
            diagram_file.close()
    loop = asyncio.get_running_loop()
    buffer = await loop.run_in_executor(None, render_strategy_card, strategy, page_text, image_bytes)
    return (discord.File(buffer, filename='playbook.png'), bool(image_bytes))

async def playbook_map_autocomplete(interaction, current, *, JsonStoreError, SETTINGS, app_commands, available_playbook_maps):
    try:
        maps = await available_playbook_maps()
    except JsonStoreError:
        maps = list(SETTINGS.competitive_maps)
    return [app_commands.Choice(name=m[:100], value=m[:100]) for m in maps if current.casefold() in m.casefold()][:25]
