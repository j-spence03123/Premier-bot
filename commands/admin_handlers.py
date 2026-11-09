"""Feature command implementations; application dependencies are injected at registration."""
from __future__ import annotations

HELP_SECTIONS = [
    ("Premier", ["schedule", "results", "mapresults", "scout", "agent", "lineup", "clearagent", "playbook"]),
    ("Players", ["register", "unregister", "accounts", "rank", "player", "recent", "play"]),
    ("Server managers", ["registeruser", "assignagent", "createplaybook", "setschedule", "matchfeed", "matchfeed_tone", "testreminder", "testplaycard", "testrankcard", "clearcache"]),
    ("Troubleshooting", ["findteam", "debug"]),
]

import asyncio
from datetime import datetime
import discord
import json
from datetime import timezone
from utils.recap_tones import normalize_tone

async def clearcache(interaction, *, cache_store):
    cache_store.clear_expiring()
    await interaction.response.send_message('Cleared. Match summaries stay cached.', ephemeral=True)

async def test_play_card(interaction, *, play_match_image, load_matchfeeds):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can use this command.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    now = datetime.now(timezone.utc)
    kevin = {'puuid': 'test-kevin-puuid', 'name': 'Kevin', 'tag': 'TEST', 'team_id': 'Red', 'agent': {'id': 'dade69b4-4f5a-8528-247b-219e5a1facd6', 'name': 'Fade'}, 'stats': {'kills': 14, 'deaths': 17, 'assists': 11, 'score': 6963, 'headshots': 49, 'bodyshots': 106, 'legshots': 12}}
    spam = {'puuid': 'test-spam-puuid', 'name': 'Spam', 'tag': 'TEST', 'team_id': 'Red', 'agent': {'id': '22697a3d-45bf-8dd7-4fec-84a9e28c69d7', 'name': 'Chamber'}, 'stats': {'kills': 7, 'deaths': 18, 'assists': 7, 'score': 3927, 'headshots': 18, 'bodyshots': 74, 'legshots': 6}}
    blue = {'puuid': 'test-opponent-puuid', 'name': 'Opponent', 'tag': 'TEST', 'team_id': 'Blue', 'agent': {'id': '707eab51-4836-f488-046a-cda6bf494859', 'name': 'Viper'}, 'stats': {'kills': 19, 'deaths': 10, 'assists': 5, 'score': 6540, 'headshots': 44, 'bodyshots': 83, 'legshots': 10}}
    kills = []
    for round_number in range(1, 22):
        killer = kevin if round_number % 2 else spam
        if round_number == 11:
            killers = [spam, spam, spam, spam, kevin]
        else:
            killers = [killer, blue, kevin if killer is spam else spam]
        for kill_index, player in enumerate(killers):
            victim = blue if player['team_id'] == 'Red' else kevin if kill_index % 2 else spam
            kills.append({'round': round_number, 'time_in_round_in_ms': 1000 + kill_index * 2500, 'killer': {'puuid': player['puuid']}, 'victim': {'puuid': victim['puuid']}})
    detail = {'metadata': {'map': {'id': '224b0a95-48b9-f703-1bd8-67aca101a61f', 'name': 'Abyss'}, 'started_at': now.isoformat(), 'game_length_in_ms': 44 * 60 * 1000}, 'teams': [{'team_id': 'Red', 'won': False, 'rounds': {'won': 8, 'lost': 13}, 'premier_roster': {'name': 'Queue'}}, {'team_id': 'Blue', 'won': True, 'rounds': {'won': 13, 'lost': 8}, 'premier_roster': {'name': 'Opponents'}}], 'players': [kevin, spam, blue], 'kills': kills}
    feed = load_matchfeeds().get(str(interaction.guild_id)) or {}
    tone = normalize_tone(feed.get('tone'))
    card = await play_match_image(detail, [kevin, spam], [kevin, spam], kevin, tone=tone)
    await interaction.followup.send(file=card, ephemeral=True)

async def test_rank_card(interaction, scenario, *, rank_change_image):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can use this command.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    previews = {'subrank': (15, 'Platinum 1', 16, 'Platinum 2', 'up'), 'promotion': (17, 'Platinum 3', 18, 'Diamond 1', 'up'), 'derank': (18, 'Diamond 1', 17, 'Platinum 3', 'down')}
    from_id, from_name, to_id, to_name, direction = previews[scenario.value]
    from_rr, to_rr, rr_change = (0, 80, -20) if direction == 'down' else (90, 15, 25)
    card = await rank_change_image(interaction.user.display_name, from_id, from_name, to_id, to_name, direction, from_rr, to_rr, rr_change)
    direction_text = 'ranked up' if direction == 'up' else 'deranked'
    await interaction.followup.send(content=f'{interaction.user.mention} {direction_text}!', file=card, ephemeral=True)

async def help_cmd(interaction, *, HELP_SECTIONS, render_help_card, tree):
    await interaction.response.defer(ephemeral=True)
    listed = {n for _, names in HELP_SECTIONS for n in names}
    sections = list(HELP_SECTIONS) + [('Other', [c.name for c in tree.get_commands() if c.name not in listed])]
    content = []
    for title, names in sections:
        lines = []
        for n in names:
            cmd = tree.get_command(n)
            if not cmd:
                continue
            params = ' '.join((f'<{p.display_name}>' if p.required else f'[{p.display_name}]' for p in cmd.parameters))
            lines.append((f"/{n}{(' ' + params if params else '')}", cmd.description))
        if lines:
            content.append((title, lines))
    loop = asyncio.get_running_loop()
    image = await loop.run_in_executor(None, render_help_card, content)
    await interaction.followup.send(file=discord.File(image, filename='help.png'), ephemeral=True)

async def debug(interaction, what, *, AFFINITY, cached_api, history):
    await interaction.response.defer(ephemeral=True)
    try:
        data = await cached_api(f'/valorant/v1/premier/seasons/{AFFINITY}', 3600) if what.value == 'schedule' else (await history())[:2]
        await interaction.followup.send(f'```json\n{json.dumps(data, indent=1)[:1800]}\n```')
    except Exception as e:
        await interaction.followup.send(str(e))
