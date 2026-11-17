"""Feature command implementations; application dependencies are injected at registration."""
from __future__ import annotations
import asyncio
from collections import Counter
from datetime import datetime, timezone
import discord
from urllib.parse import quote
from services.account_registry import MAX_SMURFS, iter_linked_accounts, matching_account, select_linked_account
from graphics.rank_profile import draw_rank_profile

async def register(interaction, riot_id, region='', *, register_account):
    await register_account(interaction, interaction.user, riot_id, region)

async def register_user(interaction, member, riot_id, region='', *, register_account):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can use this command.', ephemeral=True)
    await register_account(interaction, member, riot_id, region)

def _registration_error(accounts, user_id, requested, smurf, is_self=True):
    main = accounts.get(user_id)
    if smurf and not main:
        return ('Link your main VALORANT account with /register first.' if is_self else
                'This member needs a main VALORANT account linked with /register or /registeruser first.')
    for owner, account, is_smurf in iter_linked_accounts(accounts):
        if not matching_account(requested, account):
            continue
        if owner != user_id:
            return 'That VALORANT account is already registered to another user.'
        if smurf or is_smurf:
            return ('You already have that VALORANT account registered.' if is_self else
                    'This member already has that VALORANT account registered.')
    if smurf and len(main.get("smurfs", [])) >= MAX_SMURFS:
        subject = 'You can' if is_self else 'This member can'
        return f'{subject} link up to {MAX_SMURFS} smurfs. The account owner can remove one with /unregister.'
    return None


async def register_account(interaction, target, riot_id, region, *, AFFINITY, REGIONS, cached_api, load_accounts, save_accounts, split_riot_id, smurf=False):
    await interaction.response.defer(ephemeral=True)
    parts = split_riot_id(riot_id)
    if not parts:
        return await interaction.followup.send('Enter your Riot ID as Name#TAG, including the #.')
    name, tag = parts
    user_id = str(target.id)
    is_self = target.id == interaction.user.id
    accounts = load_accounts()
    main = accounts.get(user_id) or {}
    default_region = (main.get("region") or AFFINITY) if smurf else AFFINITY
    reg = region.lower() if region.lower() in REGIONS else default_region
    requested = {'name': name, 'tag': tag, 'region': reg}
    if error := _registration_error(accounts, user_id, requested, smurf, is_self):
        return await interaction.followup.send(error)
    data = None
    try:
        data = await cached_api(f'/valorant/v3/mmr/{reg}/pc/{quote(name)}/{quote(tag)}', 300)
    except Exception as e:
        if '404' in str(e):
            return await interaction.followup.send(f"Couldn't find {name}#{tag} in {reg}. Check the spelling and region.")
        if smurf:
            return await interaction.followup.send("Couldn't verify that Riot ID right now. Try again in a moment.")
    resolved = (data.get('account') or {}) if isinstance(data, dict) else {}
    if not isinstance(resolved, dict):
        resolved = {}
    requested['name'] = resolved.get('name') or name
    requested['tag'] = resolved.get('tag') or tag
    if resolved.get('puuid'):
        requested['puuid'] = resolved['puuid']
    accounts = load_accounts()
    if error := _registration_error(accounts, user_id, requested, smurf, is_self):
        return await interaction.followup.send(error)
    previous = accounts.get(user_id)
    if smurf:
        requested["registered_at"] = datetime.now(timezone.utc).isoformat()
        smurfs = [*previous.get("smurfs", []), requested]
        accounts[user_id] = {**previous, "smurfs": smurfs}
        save_accounts(accounts)
        message = f"Registered **{requested['name']}#{requested['tag']}** ({reg}) as smurf {len(smurfs)} of {MAX_SMURFS}"
        message += "." if is_self else f" for <@{target.id}>."
        return await interaction.followup.send(message, allowed_mentions=discord.AllowedMentions.none())
    previous_time = previous.get('registered_at') if isinstance(previous, dict) and matching_account(previous, requested) else None
    requested['registered_at'] = previous_time or datetime.now(timezone.utc).isoformat()
    if previous and previous.get("smurfs"):
        requested["smurfs"] = previous["smurfs"]
    accounts[user_id] = requested
    save_accounts(accounts)
    tier = ((data or {}).get('current') or {}).get('tier') or {} if isinstance(data, dict) else {}
    msg = f'Registered **{name}#{tag}** ({reg})'
    msg += '.' if is_self else f' for {target.display_name}.'
    if tier.get('name'):
        msg += f" Current rank: {tier['name']}."
    msg += '\nNow /rank and /player work without typing your name.' if is_self else '\nThey can now use /rank and /player without typing their name.'
    await interaction.followup.send(msg)

async def unregister(interaction, riot_id="", *, load_accounts, save_accounts):
    accounts = load_accounts()
    user_id = str(interaction.user.id)
    main = accounts.get(user_id)
    if main is None:
        return await interaction.response.send_message("You don't have an account registered.", ephemeral=True)
    if riot_id.strip():
        target = riot_id.strip().casefold()
        smurfs = main.get("smurfs", [])
        remaining = [account for account in smurfs if f"{account['name']}#{account['tag']}".casefold() != target]
        if len(remaining) == len(smurfs):
            return await interaction.response.send_message(
                "That Riot ID isn't one of your registered smurfs. Use /accounts to check.", ephemeral=True,
            )
        accounts[user_id] = {**main, "smurfs": remaining}
        message = 'Your smurf was unlinked.'
    else:
        accounts.pop(user_id)
        message = 'Your main account and registered smurfs were unlinked.' if main.get("smurfs") else 'Your account was unlinked.'
    save_accounts(accounts)
    await interaction.response.send_message(message, ephemeral=True)

async def accounts_cmd(interaction, *, load_accounts):
    accounts = load_accounts()
    if not accounts:
        return await interaction.response.send_message('Nobody has registered yet. Use /register.')
    lines = []
    slots = Counter()
    for uid, account, smurf in iter_linked_accounts(accounts):
        label = "Main"
        if smurf:
            slots[uid] += 1
            label = f"Smurf {slots[uid]}"
        lines.append(f"<@{uid}> → {account['name']}#{account['tag']} ({account.get('region', '')}) · {label}")
    await interaction.response.send_message('\n'.join(lines)[:1900], allowed_mentions=discord.AllowedMentions.none())

def _profile_account(caller, member, name, tag, region, account_slot, load_accounts, resolve_player):
    if account_slot == "Main" or name or tag:
        return resolve_player(caller, member, name, tag, region)
    account = select_linked_account(load_accounts().get(str((member or caller).id)), account_slot)
    if account:
        return account["name"], account["tag"], region or account.get("region") or ""
    return None


async def rank_cmd(interaction, name='', tag='', region='', member=None, *, AFFINITY, NO_PLAYER, REGIONS, cached_api, icon_maps, icon_img, load_accounts, resolve_player, account_slot="Main"):
    await interaction.response.defer()
    if member and (not load_accounts().get(str(member.id))):
        return await interaction.followup.send(f'{member.display_name} has not linked a Valorant account yet. They can use /register first.')
    who = _profile_account(interaction.user, member, name, tag, region, account_slot, load_accounts, resolve_player)
    if not who:
        return await interaction.followup.send(NO_PLAYER if account_slot == "Main" else f"No account is linked in {account_slot}.")
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

async def player_cmd(interaction, name='', tag='', mode=None, region='', member=None, *, AFFINITY, NO_PLAYER, REGIONS, cached_api, icon_img, icon_maps, load_accounts, parse_stored, render_player_history, resolve_player, account_slot="Main"):
    await interaction.response.defer()
    if member and (not load_accounts().get(str(member.id))):
        return await interaction.followup.send(f'{member.display_name} has not linked a Valorant account yet. They can use /register first.')
    who = _profile_account(interaction.user, member, name, tag, region, account_slot, load_accounts, resolve_player)
    if not who:
        return await interaction.followup.send(NO_PLAYER if account_slot == "Main" else f"No account is linked in {account_slot}.")
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
