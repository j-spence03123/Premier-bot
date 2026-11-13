"""Feature command implementations; application dependencies are injected at registration."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import discord
from urllib.parse import quote
from services.account_registry import matching_account
from graphics.rank_profile import draw_rank_profile

async def register(interaction, riot_id, region='', *, register_account):
    await register_account(interaction, interaction.user, riot_id, region)

async def register_user(interaction, member, riot_id, region='', *, register_account):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can use this command.', ephemeral=True)
    await register_account(interaction, member, riot_id, region)

async def register_account(interaction, target, riot_id, region, *, AFFINITY, REGIONS, cached_api, load_accounts, save_accounts, split_riot_id):
    await interaction.response.defer(ephemeral=True)
    parts = split_riot_id(riot_id)
    if not parts:
        return await interaction.followup.send('Enter your Riot ID as Name#TAG, including the #.')
    name, tag = parts
    reg = region.lower() if region.lower() in REGIONS else AFFINITY
    requested = {'name': name, 'tag': tag, 'region': reg}
    accounts = load_accounts()
    if any(uid != str(target.id) and isinstance(account, dict) and matching_account(requested, account)
           for uid, account in accounts.items()):
        return await interaction.followup.send('That VALORANT account is already registered to another user.')
    data = None
    try:
        data = await cached_api(f'/valorant/v3/mmr/{reg}/pc/{quote(name)}/{quote(tag)}', 300)
    except Exception as e:
        if '404' in str(e):
            return await interaction.followup.send(f"Couldn't find {name}#{tag} in {reg}. Check the spelling and region.")
    resolved = (data.get('account') or {}) if isinstance(data, dict) else {}
    if not isinstance(resolved, dict):
        resolved = {}
    requested['name'] = resolved.get('name') or name
    requested['tag'] = resolved.get('tag') or tag
    if resolved.get('puuid'):
        requested['puuid'] = resolved['puuid']
    accounts = load_accounts()
    if any(uid != str(target.id) and isinstance(account, dict) and matching_account(requested, account)
           for uid, account in accounts.items()):
        return await interaction.followup.send('That VALORANT account is already registered to another user.')
    previous = accounts.get(str(target.id))
    previous_time = previous.get('registered_at') if isinstance(previous, dict) and matching_account(previous, requested) else None
    requested['registered_at'] = previous_time or datetime.now(timezone.utc).isoformat()
    accounts[str(target.id)] = requested
    save_accounts(accounts)
    tier = ((data or {}).get('current') or {}).get('tier') or {} if isinstance(data, dict) else {}
    is_self = target.id == interaction.user.id
    msg = f'Registered **{name}#{tag}** ({reg})'
    msg += '.' if is_self else f' for {target.display_name}.'
    if tier.get('name'):
        msg += f" Current rank: {tier['name']}."
    msg += '\nNow /rank and /player work without typing your name.' if is_self else '\nThey can now use /rank and /player without typing their name.'
    await interaction.followup.send(msg)

async def unregister(interaction, *, load_accounts, save_accounts):
    accounts = load_accounts()
    if accounts.pop(str(interaction.user.id), None) is None:
        return await interaction.response.send_message("You don't have an account registered.", ephemeral=True)
    save_accounts(accounts)
    await interaction.response.send_message('Your account was unlinked.', ephemeral=True)

async def accounts_cmd(interaction, *, load_accounts):
    accounts = load_accounts()
    if not accounts:
        return await interaction.response.send_message('Nobody has registered yet. Use /register.')
    lines = [f"<@{uid}> → {a['name']}#{a['tag']} ({a.get('region', '')})" for uid, a in accounts.items()]
    await interaction.response.send_message('\n'.join(lines)[:1900], allowed_mentions=discord.AllowedMentions.none())

async def rank_cmd(interaction, name='', tag='', region='', member=None, *, AFFINITY, NO_PLAYER, REGIONS, cached_api, icon_maps, icon_img, load_accounts, resolve_player):
    await interaction.response.defer()
    if member and (not load_accounts().get(str(member.id))):
        return await interaction.followup.send(f'{member.display_name} has not linked a Valorant account yet. They can use /register first.')
    who = resolve_player(interaction.user, member, name, tag, region)
    if not who:
        return await interaction.followup.send(NO_PLAYER)
    name, tag, region = who
    reg = region.lower() if region.lower() in REGIONS else AFFINITY
    try:
        d = await cached_api(f'/valorant/v3/mmr/{reg}/pc/{quote(name)}/{quote(tag)}', 300)
    except Exception as e:
        return await interaction.followup.send(f"Couldn't fetch rank: {str(e)[:300]}")
    cur, peak = (d.get('current') or {}, d.get('peak') or {})
    try:
        icons = (await icon_maps()).get('tiers', {})
    except Exception as exc:
        print(f'Rank icon catalog unavailable: {exc}')
        icons = {}
    current_id = (cur.get('tier') or {}).get('id')
    peak_id = (peak.get('tier') or {}).get('id')
    current_icon, peak_icon = await asyncio.gather(
        icon_img(icons.get(str(current_id)), 132), icon_img(icons.get(str(peak_id)), 132))
    loop = asyncio.get_running_loop()
    image = await loop.run_in_executor(None, draw_rank_profile, f'{name}#{tag}', cur, peak, current_icon, peak_icon)
    await interaction.followup.send(file=discord.File(image, filename='rank.png'))

async def player_cmd(interaction, name='', tag='', mode=None, region='', member=None, *, AFFINITY, NO_PLAYER, REGIONS, cached_api, icon_img, icon_maps, load_accounts, parse_stored, render_player_history, resolve_player):
    await interaction.response.defer()
    if member and (not load_accounts().get(str(member.id))):
        return await interaction.followup.send(f'{member.display_name} has not linked a Valorant account yet. They can use /register first.')
    who = resolve_player(interaction.user, member, name, tag, region)
    if not who:
        return await interaction.followup.send(NO_PLAYER)
    name, tag, region = who
    reg = region.lower() if region.lower() in REGIONS else AFFINITY
    mode_value = mode.value if mode else 'competitive'
    try:
        data = await cached_api(f'/valorant/v1/stored-matches/{reg}/{quote(name)}/{quote(tag)}', 300, mode=mode_value, size=10)
    except Exception as e:
        return await interaction.followup.send(f"Couldn't fetch matches: {str(e)[:300]}")
    rows = sorted((parse_stored(m) for m in data or []), key=lambda r: r['started'] or '', reverse=True)
    if not rows:
        return await interaction.followup.send(f'No {mode_value} matches found for {name}#{tag}.')
    try:
        mmr = await cached_api(f'/valorant/v3/mmr/{reg}/pc/{quote(name)}/{quote(tag)}', 300)
    except Exception as exc:
        print(f'Player rank unavailable: {exc}')
        mmr = None
    try:
        catalog = await icon_maps()
    except Exception as exc:
        print(f'Player history agent catalog unavailable: {exc}')
        catalog = {}
    by_name = {agent_name.casefold(): agent_id for agent_id, agent_name in catalog.get('agent_names', {}).items()}
    icon_urls = {}
    for row in rows:
        key = (row.get('agent_id') or row.get('agent') or '').casefold()
        agent_id = row.get('agent_id') or by_name.get((row.get('agent') or '').casefold())
        url = catalog.get('agents', {}).get(agent_id)
        if not url and agent_id:
            url = f'https://media.valorant-api.com/agents/{agent_id}/displayicon.png'
        if key and url:
            icon_urls[key] = url
    loaded = await asyncio.gather(*(icon_img(url, 68) for url in icon_urls.values()))
    icons = dict(zip(icon_urls, loaded))
    tier_id = (((mmr or {}).get('current') or {}).get('tier') or {}).get('id')
    rank_icon = await icon_img(catalog.get('tiers', {}).get(str(tier_id)), 84)
    loop = asyncio.get_running_loop()
    image = await loop.run_in_executor(None, render_player_history, name, tag, mode_value, rows, icons, mmr, rank_icon)
    await interaction.followup.send(file=discord.File(image, filename='player-history.png'))
