"""Feature command implementations; application dependencies are injected at registration."""
from __future__ import annotations
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError
import asyncio
from datetime import datetime
import discord
import json
from urllib.parse import quote
from datetime import timedelta
from datetime import timezone

async def schedule(interaction, *, load_season, schedule_card_file):
    await interaction.response.defer()
    season = load_season()
    if not season:
        return await interaction.followup.send('No season schedule is configured.')
    today = datetime.now(timezone.utc).date().isoformat()
    card = await schedule_card_file(season, today)
    await interaction.followup.send(file=card)

async def setschedule(interaction, days='', local_time='', timezone_name='', channel=None, *, load_queue_schedules, save_queue_schedules):
    if not interaction.guild:
        return await interaction.response.send_message('Use this command in a server.', ephemeral=True)
    if not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can set the schedule.', ephemeral=True)
    supplied = (days.strip(), local_time.strip(), timezone_name.strip())
    if any(supplied) and (not all(supplied)):
        return await interaction.response.send_message('For reminders, provide days, local_time, and timezone_name together.', ephemeral=True)
    if not all(supplied):
        return await interaction.response.send_message('Provide days, local_time, and timezone_name together to configure queue reminders.', ephemeral=True)
    if all(supplied):
        weekdays = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
        day_lookup = {name.casefold(): i for i, name in enumerate(weekdays)}
        day_lookup.update({name[:3].casefold(): i for i, name in enumerate(weekdays)})
        try:
            zone = ZoneInfo(timezone_name.strip())
        except (ZoneInfoNotFoundError, ValueError):
            return await interaction.response.send_message("I don't recognize that IANA time zone.", ephemeral=True)
        try:
            parsed_time = datetime.strptime(local_time.strip(), '%H:%M').time()
        except ValueError:
            return await interaction.response.send_message('Use 24-hour HH:MM for local_time, such as 20:00.', ephemeral=True)
        day_values = []
        for raw_day in days.split(','):
            day = day_lookup.get(raw_day.strip().casefold())
            if day is None:
                return await interaction.response.send_message('Use weekday names separated by commas.', ephemeral=True)
            if day not in day_values:
                day_values.append(day)
        if not day_values:
            return await interaction.response.send_message('Add at least one queue day.', ephemeral=True)
        target = channel or (interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None)
        if target is None:
            return await interaction.response.send_message('Choose a text channel for reminders.', ephemeral=True)
        configs = load_queue_schedules()
        configs[str(interaction.guild_id)] = {'days': sorted(day_values), 'time': parsed_time.strftime('%H:%M'), 'timezone': zone.key, 'channel_id': target.id, 'last_reminder_date': None}
        save_queue_schedules(configs)
    day_names = ', '.join((weekdays[d] for d in sorted(set(day_values))))
    await interaction.response.send_message(f"Reminders set for {day_names} at {parsed_time.strftime('%H:%M')} {zone.key} in {target.mention}, 30 minutes before queue.", ephemeral=True)

async def testreminder(interaction, channel=None, *, build_lineup_reminder, load_queue_schedules):
    if not interaction.guild:
        return await interaction.response.send_message('Use this command in a server.', ephemeral=True)
    if not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can test reminders.', ephemeral=True)
    config = load_queue_schedules().get(str(interaction.guild_id))
    target = channel
    if target is None and config:
        target = interaction.guild.get_channel(int(config.get('channel_id', 0)))
    if target is None:
        return await interaction.response.send_message('No reminder channel is configured. Set one with /setschedule, or choose a channel for this test.', ephemeral=True)
    label = 'Test queue reminder'
    if config:
        try:
            zone = ZoneInfo(config['timezone'])
            hour, minute = map(int, config['time'].split(':'))
            days = ', '.join((('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d] for d in config['days']))
            label = f'Test reminder · {days} at {hour:02d}:{minute:02d} {zone.key}'
        except (KeyError, ValueError, ZoneInfoNotFoundError):
            pass
    await interaction.response.defer(ephemeral=True)
    embed, picked_user_ids, lineup_file = await build_lineup_reminder(label, 'This is a test reminder.', interaction.guild)
    mentions = ' '.join((f'<@{uid}>' for uid in picked_user_ids))
    content = 'Test queue reminder. Players with agent picks:' + (f' {mentions}' if mentions else ' Nobody has picked an agent yet.')
    send_args = {'content': content, 'embed': embed, 'allowed_mentions': discord.AllowedMentions(users=[discord.Object(id=uid) for uid in picked_user_ids])}
    if lineup_file:
        send_args['file'] = lineup_file
    await target.send(**send_args)
    await interaction.followup.send(f'Test reminder posted in {target.mention}.', ephemeral=True)

async def results(interaction, days=7, *, ScoreboardView, TEAM_NAME, history, load_summaries, parse_time, render_scoreboard, ts):
    await interaction.response.defer()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = [m for m in await history() if (parse_time(m.get('started_at')) or cutoff) >= cutoff]
        if not recent:
            return await interaction.followup.send(f'No Premier matches in the last {days} days.')
        pairs = await load_summaries(recent[:10])
    except Exception as e:
        return await interaction.followup.send(f"Couldn't fetch results: {e}")
    embed = discord.Embed(title=f"{TEAM_NAME or 'Premier'} results, last {days} days", colour=16729685)
    wins = 0
    for m, s in pairs:
        if 'error' in s:
            embed.add_field(name='Match', value=f"Couldn't load details: {s['error'][:100]}", inline=False)
            continue
        wins += s['won']
        top = s['rows'][0] if s['rows'] else None
        delta = (m.get('points_after', 0) or 0) - (m.get('points_before', 0) or 0)
        embed.add_field(name=f"{('WIN' if s['won'] else 'LOSS')} {s['score']} on {s['map']}", value=f"{ts(s['started'])}" + (f'\nPoints: {delta:+d}' if 'points_after' in m else '') + (f"\nTop: {top['name']} ({top['agent']}) {top['k']}/{top['d']}/{top['a']}, ACS {top['acs']}" if top else ''), inline=False)
    embed.set_footer(text=f'{wins}W - {len(pairs) - wins}L')
    good = [(m, s) for m, s in pairs if 'error' not in s]
    if not good:
        return await interaction.followup.send(embed=embed)
    file = await render_scoreboard(good[0][1], 'latest.png')
    embed.set_image(url='attachment://latest.png')
    view = ScoreboardView(good, embed) if len(good) > 1 else discord.utils.MISSING
    await interaction.followup.send(embed=embed, file=file, view=view)

async def mapresults(interaction, map_name, limit=3, *, history, load_summaries, render_scoreboard):
    await interaction.response.defer()
    try:
        pairs = await load_summaries((await history())[:25])
    except Exception as e:
        return await interaction.followup.send(f"Couldn't fetch results: {e}")
    on_map = [(m, s) for m, s in pairs if 'error' not in s and s['map'].lower() == map_name.lower()]
    if not on_map:
        return await interaction.followup.send(f'No recent Premier matches found on {map_name}.')
    wins = sum((s['won'] for _, s in on_map))
    embeds = [discord.Embed(title=f"{on_map[0][1]['map']}: {wins}W - {len(on_map) - wins}L", description=f'{len(on_map)} recent matches on this map', colour=16729685)]
    files = []
    for i, (_, s) in enumerate(on_map[:max(1, min(limit, 5))]):
        e = discord.Embed(title=f"{('WIN' if s['won'] else 'LOSS')} {s['score']}", colour=3066993 if s['won'] else 15158332)
        files.append(await render_scoreboard(s, f'm{i}.png'))
        e.set_image(url=f'attachment://m{i}.png')
        embeds.append(e)
    await interaction.followup.send(embeds=embeds, files=files)

async def findteam(interaction, riot_name, riot_tag, *, AFFINITY, api):
    await interaction.response.defer(ephemeral=True)
    try:
        data = await api(f'/valorant/v2/premier/players/{AFFINITY}/{quote(riot_name)}/{quote(riot_tag)}')
        await interaction.followup.send(f'```json\n{json.dumps(data, indent=1)[:1800]}\n```')
    except Exception as e:
        await interaction.followup.send(str(e)[:1800])

async def scout(interaction, team_name, team_tag, acts=1, *, AFFINITY, api, cache_store, cached, cached_api, extract_premier_seasons, match_detail, parse_time, summarise, time, valorant_acts):
    await interaction.response.defer()
    team_name, team_tag = (team_name.strip(), team_tag.strip())
    if not team_name or not team_tag:
        return await interaction.followup.send('Provide both the Premier team name and tag.')
    team_endpoint = f'/valorant/v1/premier/{quote(team_name)}/{quote(team_tag)}'
    team_v2_endpoint = f'/valorant/v2/premier/teams/{AFFINITY}/{quote(team_name)}/{quote(team_tag)}'
    try:
        try:
            team = await cached_api(team_v2_endpoint, 86400)
        except Exception:
            team = await cached_api(team_endpoint, 86400)
        premier_season_data = await cached_api(f'/valorant/v1/premier/seasons/{AFFINITY}', 86400)
        act_list = await valorant_acts()
    except Exception as exc:
        return await interaction.followup.send(f"Couldn't look up **{team_name}#{team_tag}**: {str(exc)[:300]}")
    selected_acts = act_list[:acts]
    if not selected_acts:
        return await interaction.followup.send("Couldn't find current or past VALORANT acts from the VALORANT API.")
    premier_seasons = extract_premier_seasons(premier_season_data)
    if not premier_seasons:
        return await interaction.followup.send("Couldn't read Premier match history seasons from HenrikDev.")
    premier_seasons = premier_seasons[:min(len(premier_seasons), max(2, int(acts) * 2))]
    team_id = team.get('id') or team.get('team_id')
    team_members_data = team.get('member') or team.get('members') or []
    member_keys = set()
    for player in team_members_data:
        if player.get('puuid'):
            member_keys.add(player['puuid'].lower())
        if player.get('name'):
            member_keys.add(f"{player['name']}#{player.get('tag', '')}".lower())

    async def season_history(season):
        cache_key = f"scout-history:{AFFINITY}:{team_name.casefold()}#{team_tag.casefold()}:{season['id']}"

        async def fetch_history():
            try:
                data = await api(team_endpoint + '/history', season=season['id'])
                return data.get('league_matches', []) if isinstance(data, dict) else data
            except Exception as exc:
                message = str(exc)
                if '404' in message and 'Premier Team not found' in message:
                    return []
                print(f"Scout history lookup failed for season {season['id']}: {message}")
                return []
        return await cached(cache_key, 86400, fetch_history)
    history_lists = await asyncio.gather(*(season_history(season) for season in premier_seasons))
    act_windows = [(act['start'], act['end']) for act in selected_acts]
    match_records = {}
    for season_matches in history_lists:
        for match in season_matches if isinstance(season_matches, list) else []:
            match_id = match.get('id') or match.get('match_id') or (match.get('meta') or {}).get('id')
            if not match_id:
                continue
            started = parse_time(match.get('started_at') or (match.get('meta') or {}).get('started_at'))
            if started:
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if not any((start <= started <= end for start, end in act_windows)):
                    continue
            match_records.setdefault(str(match_id), match)
    matches = list(match_records.values())
    if not matches:
        act_names = ', '.join((act['name'] for act in selected_acts))
        return await interaction.followup.send(f'No Premier matches found for **{team_name}#{team_tag}** during {act_names}.')
    detail_gate = asyncio.Semaphore(1)

    async def summarize_match(match):
        match_id = match.get('id') or match.get('match_id') or (match.get('meta') or {}).get('id')
        if not match_id:
            return None
        try:
            cache_key = f'scoutmatch:{match_id}'
            hit = cache_store.peek(cache_key)
            is_fresh = hit and (hit.get('ttl') is None or time.time() - hit['t'] < hit['ttl'])
            if is_fresh:
                detail = await cached(cache_key, None, lambda: match_detail(match_id))
            else:
                async with detail_gate:
                    await asyncio.sleep(1.25)
                    detail = await cached(cache_key, None, lambda: match_detail(match_id))
            summary = summarise(detail, member_keys, team_id, team_name, team_tag)
            if not summary['rows']:
                return None
            started = parse_time(summary.get('started'))
            if not started:
                return None
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if not any((start <= started <= end for start, end in act_windows)):
                return None
            return summary
        except Exception as exc:
            print(f'Scout match {match_id} failed: {exc}')
            return None
    summaries = await asyncio.gather(*(summarize_match(match) for match in matches))
    summaries = [item for item in summaries if item]
    if not summaries:
        return await interaction.followup.send(f"Found **{team_name}#{team_tag}**, but couldn't match its Premier history to detailed match data in the selected acts.")
    maps = {}
    wins = 0
    for summary in summaries:
        won = summary['won']
        wins += int(won)
        record = maps.setdefault(summary['map'], {'wins': 0, 'losses': 0, 'agents': {}})
        record['wins' if won else 'losses'] += 1
        for row in summary['rows']:
            agent = row.get('agent') or 'Unknown'
            if agent != '?':
                record['agents'][agent] = record['agents'].get(agent, 0) + 1
    total = len(summaries)
    act_names = ', '.join((act['name'] for act in selected_acts))
    embed = discord.Embed(title=f'Premier scout · {team_name}#{team_tag}', description=f'**Record:** {wins}W–{total - wins}L · **Win rate:** {wins / total:.0%}\nBased on {total} detailed matches across {len(selected_acts)} VALORANT act(s): {act_names}.', colour=16729685)
    for map_name, record in sorted(maps.items(), key=lambda item: item[0].casefold()):
        picks = sorted(record['agents'].items(), key=lambda item: (-item[1], item[0].casefold()))
        pick_text = ', '.join((f'{agent} ×{count}' for agent, count in picks)) or 'No agent data'
        embed.add_field(name=f"{map_name} · {record['wins']}W–{record['losses']}L", value=f'Agent picks: {pick_text}'[:1024], inline=False)
    embed.set_footer(text='Agent pick counts are pooled across players and matches on each map.')
    await interaction.followup.send(embed=embed)
