import asyncio
import json
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from config import REGIONS, SETTINGS
from commands import (install_command_cogs, matchfeed_commands, premier_handlers, player_handlers,
                      agent_handlers, playbook_handlers, admin_handlers)
from commands.context import CommandContext
from commands.recent import recent_scoreboard_view as make_recent_scoreboard_view
from commands.scoreboard_view import ScoreboardView
from commands.playbook_views import PlaybookView
from commands.playbook_admin import PlaybookAdminView
from graphics.assets import load_icon_image
from graphics.help_card import render_help_card
from graphics.lineup import render_lineup_card
from graphics.match_card import draw_play_result
from graphics.player_history import render_player_history
from graphics.playbook_card import render_playbook_card, render_strategy_card
from graphics.rank_change import draw_rank_change_card
from graphics.schedule import render_schedule_card
from graphics.scoreboard import draw_scoreboard
from services import (background_tasks, match_images, asset_helpers, premier_helpers, discord_helpers,
                      account_helpers, agent_helpers, playbook_helpers)
from services.bot_state import BotState
from services.cache import JsonCache
from services.ai_recap import generate_recap
from services.json_store import JsonStoreError, read_json
from services.match_history import MatchHistoryService
from services.playbook_service import PlaybookDataError, PlaybookService
from services.valorant_api import HenrikDevClient
from utils.formatting import fmt_range, parse_time
from utils.premier_seasons import extract_premier_seasons
from utils.queue_schedule import next_queue_start
from utils.riot_id import split_riot_id
from utils.stored_matches import parse_stored
from utils.statistics import summarise_match

TOKEN = SETTINGS.discord_token
HENRIK_KEY = SETTINGS.henrik_api_key
TEAM_ID = SETTINGS.team_id
TEAM_NAME = SETTINGS.team_name
TEAM_TAG = SETTINGS.team_tag
ROSTER = list(SETTINGS.roster)
AFFINITY = SETTINGS.affinity
GUILD_ID = SETTINGS.guild_id
BASE = SETTINGS.api_base
X_BEARER = SETTINGS.x_bearer
X_USERNAME = SETTINGS.x_username
X_KEYWORD = SETTINGS.x_keyword
CACHE_FILE = SETTINGS.cache_file
QUEUE_SCHEDULE_FILE = SETTINGS.queue_schedule_file
SEASON_FILE = SETTINGS.season_file
PLAYBOOK_FILE = SETTINGS.playbook_file
ACCOUNTS_FILE = SETTINGS.accounts_file
AGENTS_FILE = SETTINGS.agents_file
PLAY_SESSIONS_FILE = SETTINGS.play_sessions_file
MATCHFEEDS_FILE = SETTINGS.matchfeeds_file
RANKSTATES_FILE = SETTINGS.rankstates_file
ICON_DIR = SETTINGS.icon_dir

intents = discord.Intents.default()
class BotClient(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._background_tasks_started = False
        self._command_cogs_loaded = False
        self._background_tasks = []
        self._commands_synced = False
        self._icons_warmed = False
        self._icon_warm_task = None

    async def setup_hook(self):
        await super().setup_hook()
        removed = state.remove_duplicate_accounts()
        if removed:
            print(f"Removed {len(removed)} duplicate account registration(s); a backup was saved.")
        if not self._command_cogs_loaded:
            await install_command_cogs(self, make_command_context())
            self._command_cogs_loaded = True
        if self._background_tasks_started:
            return
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        self.http_session = aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300))
        self.x_session = aiohttp.ClientSession(timeout=timeout)
        api_client.bind_session(self.http_session)
        self.queue_reminder_task = asyncio.create_task(queue_reminder_loop(), name="queue-reminders")
        self.play_session_task = asyncio.create_task(play_session_loop(), name="play-sessions")
        self.matchfeed_task = asyncio.create_task(matchfeed_loop(), name="match-feed")
        self._background_tasks = [
            self.queue_reminder_task,
            self.play_session_task,
            self.matchfeed_task,
        ]
        self._background_tasks_started = True

    async def close(self):
        tasks = list(self._background_tasks)
        if self._icon_warm_task is not None:
            tasks.append(self._icon_warm_task)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for session in (getattr(self, "http_session", None), getattr(self, "x_session", None)):
            if session and not session.closed:
                await session.close()
        await cache_store.flush_pending()
        await super().close()


client = BotClient(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
tree = client.tree
state = BotState(SETTINGS)
cache_store = JsonCache(CACHE_FILE)
api_client = HenrikDevClient(BASE, HENRIK_KEY, max_concurrency=3)
_icon_locks = {}


# ---------- API helpers ----------
async def api(path: str, **params):
    return await api_client.get(path, **params)


async def cached(key, ttl, fn):
    return await cache_store.get(key, ttl, fn)


def cached_api(path, ttl, **params):
    return cache_store.get(path + json.dumps(params, sort_keys=True), ttl, lambda: api(path, **params))


match_history = MatchHistoryService(
    cached_api, api, AFFINITY, ROSTER, TEAM_ID, TEAM_NAME, TEAM_TAG
)


async def x_get(path, **params):
    async with client.x_session.get(
        "https://api.twitter.com/2" + path,
        headers={"Authorization": f"Bearer {X_BEARER}"},
        params=params,
    ) as r:
        body = await r.json()
        if r.status != 200:
            raise RuntimeError(f"X API {r.status}: {body}")
        return body


async def latest_schedule_tweet():
    return await premier_helpers.latest_schedule_tweet(X_BEARER=X_BEARER, X_KEYWORD=X_KEYWORD, X_USERNAME=X_USERNAME, cached=cached, x_get=x_get)


def ts(d, style='F'):
    return premier_helpers.ts(d, style, parse_time=parse_time)


def team_path():
    return match_history.team_path()


async def team_data():
    return await match_history.team_data()


async def team_members():
    return await match_history.team_members()


async def history_from_players():
    return await match_history.history_from_players()


async def history():
    return await match_history.history()


async def match_detail(match_id: str, region=None):
    return await match_history.match_detail(match_id, region)


def summarise(detail: dict, members: set, premier_team_id=None, premier_team_name=None,
              premier_team_tag=None):
    return summarise_match(
        detail, members, premier_team_id, premier_team_name, premier_team_tag, TEAM_NAME
    )


def player_table(rows):
    return premier_helpers.player_table(rows)


# ---------- Scoreboard image ----------
# ---------- External image assets ----------


async def icon_maps():
    return await asset_helpers.icon_maps(cached=cached, client=client)


async def icon_img(url, size):
    return await asset_helpers.icon_img(url, size, ICON_DIR=ICON_DIR, _icon_locks=_icon_locks, client=client, load_icon_image=load_icon_image)


COLS = [("ACS", 500), ("K", 565), ("D", 610), ("A", 655), ("+/-", 715), ("K/D", 780), ("ADR", 845), ("HS%", 910), ("FB", 965)]
GREY = (150, 162, 175)
WHITE = (240, 244, 248)
PLAY_TAG_STYLES = {
    "MVP": ((109, 79, 38), (255, 214, 128)),
    "LVP": ((105, 39, 45), (255, 151, 157)),
    "VICTIM": ((67, 68, 78), (211, 214, 224)),
    "ACE": ((141, 91, 32), (255, 223, 132)),
    "QUAD": ((119, 93, 33), (255, 218, 119)),
    "ENTRY": ((39, 78, 122), (163, 205, 255)),
    "DINK MACHINE": ((89, 59, 126), (219, 183, 255)),
    "ASSIST KING": ((35, 100, 91), (153, 235, 214)),
    "DAMAGE DEALER": ((137, 68, 37), (255, 187, 143)),
    "SURVIVOR": ((48, 98, 63), (170, 237, 178)),
    "CLUTCH": ((123, 55, 92), (255, 172, 218)),
}


async def current_rank(name, tag):
    return await premier_helpers.current_rank(name, tag, AFFINITY=AFFINITY, cached_api=cached_api)


async def render_scoreboard(s, filename):
    return await premier_helpers.render_scoreboard(s, filename, current_rank=current_rank, draw_scoreboard=draw_scoreboard, icon_img=icon_img, icon_maps=icon_maps)


async def load_summaries(matches):
    return await premier_helpers.load_summaries(matches, cached=cached, match_detail=match_detail, summarise=summarise, team_members=team_members)


# ---------- Commands ----------
def load_season():
    return premier_helpers.load_season(JsonStoreError=JsonStoreError, SEASON_FILE=SEASON_FILE, read_json=read_json)


def season_maps():
    return premier_helpers.season_maps(load_season=load_season)


async def valorant_map_catalog():
    return await asset_helpers.valorant_map_catalog(cached=cached, client=client)


async def map_background_path(map_uuid, map_name='Unknown'):
    return await asset_helpers.map_background_path(map_uuid, map_name, ICON_DIR=ICON_DIR, client=client)


async def schedule_card_file(season, today):
    return await premier_helpers.schedule_card_file(season, today, map_background_path=map_background_path, render_schedule_card=render_schedule_card, valorant_map_catalog=valorant_map_catalog)


load_queue_schedules = state.load_queue_schedules


save_queue_schedules = state.save_queue_schedules


async def discord_display_name(guild, user_id):
    return await discord_helpers.discord_display_name(guild, user_id, client=client)


async def build_lineup_reminder(title, intro, guild=None):
    return await discord_helpers.build_lineup_reminder(title, intro, guild, current_week=current_week, discord_display_name=discord_display_name, fmt_range=fmt_range, lineup_card_file=lineup_card_file, load_agents=load_agents, matching_map_key=matching_map_key)


async def queue_reminder_loop():
    return await background_tasks.queue_reminder_loop(
        client=client,
        load_queue_schedules=load_queue_schedules,
        build_lineup_reminder=build_lineup_reminder,
        next_queue_start=next_queue_start,
        save_queue_schedules=save_queue_schedules,
    )


async def map_autocomplete(interaction: discord.Interaction, current: str):
    return await premier_helpers.map_autocomplete(interaction, current, app_commands=app_commands, season_maps=season_maps)


WIN, LOSS, DRAW = "\u2705", "\u274c", "\u2796"


load_accounts = state.load_accounts


save_accounts = state.save_accounts


load_play_sessions = state.load_play_sessions


save_play_sessions = state.save_play_sessions


load_matchfeeds = state.load_matchfeeds


save_matchfeeds = state.save_matchfeeds


def save_matchfeed_progress(snapshot, guild_key):
    return account_helpers.save_matchfeed_progress(snapshot, guild_key, load_matchfeeds=load_matchfeeds, save_matchfeeds=save_matchfeeds)


load_rank_states = state.load_rank_states


save_rank_states = state.save_rank_states


async def play_session_loop():
    return await background_tasks.play_session_loop(
        client=client,
        load_play_sessions=load_play_sessions,
        load_matchfeeds=load_matchfeeds,
        load_accounts=load_accounts,
        cached_api=cached_api,
        cached=cached,
        match_detail=match_detail,
        parse_time=parse_time,
        play_match_image=play_match_image,
        save_play_sessions=save_play_sessions,
        AFFINITY=AFFINITY,
    )


async def matchfeed_loop():
    return await background_tasks.matchfeed_loop(
        client=client,
        load_matchfeeds=load_matchfeeds,
        load_accounts=load_accounts,
        load_rank_states=load_rank_states,
        save_rank_states=save_rank_states,
        cached_api=cached_api,
        cached=cached,
        match_detail=match_detail,
        parse_time=parse_time,
        play_match_image=play_match_image,
        rank_change_image=rank_change_image,
        save_matchfeed_progress=save_matchfeed_progress,
        AFFINITY=AFFINITY,
    )


async def play_match_image(detail, queued_players, all_teammates, representative, summary_players=None, tone="no_filter"):
    return await match_images.play_match_image(
        detail, queued_players, all_teammates, representative, summary_players, tone,
        map_background_path=map_background_path, icon_maps=icon_maps, icon_img=icon_img,
        session=client.http_session, api_key=SETTINGS.groq_api_key, model=SETTINGS.groq_model,
        generate_recap=generate_recap, draw_play_result=draw_play_result,
    )


async def rank_change_image(player_name, from_id, from_name, to_id, to_name, direction,
                            from_rr=None, to_rr=None, rr_change=None):
    return await match_images.rank_change_image(
        player_name, from_id, from_name, to_id, to_name, direction, from_rr, to_rr, rr_change,
        icon_maps=icon_maps, icon_img=icon_img, draw_rank_change_card=draw_rank_change_card,
    )


async def recent_scoreboard_view(detail, target):
    return await make_recent_scoreboard_view(detail, target, map_background_path=map_background_path,
                                             icon_maps=icon_maps, icon_img=icon_img)


def resolve_player(caller, member, name, tag, region):
    return account_helpers.resolve_player(caller, member, name, tag, region, load_accounts=load_accounts, split_riot_id=split_riot_id)


NO_PLAYER = "Give a name and tag (or Name#TAG), mention a member who has registered, or use /register to link your own account."


async def register_account(interaction, target, riot_id, region):
    return await player_handlers.register_account(interaction, target, riot_id, region, AFFINITY=AFFINITY, REGIONS=REGIONS, cached_api=cached_api, load_accounts=load_accounts, save_accounts=save_accounts, split_riot_id=split_riot_id)


async def valorant_acts():
    return await premier_helpers.valorant_acts(cached=cached, client=client, parse_time=parse_time)


FALLBACK_AGENTS = [
    "Astra", "Breach", "Brimstone", "Chamber", "Clove", "Cypher", "Deadlock", "Fade", "Gekko", "Harbor",
    "Iso", "Jett", "KAY/O", "Killjoy", "Neon", "Omen", "Phoenix", "Raze", "Reyna", "Sage", "Skye",
    "Sova", "Tejo", "Viper", "Vyse", "Waylay", "Yoru",
]


async def agent_names():
    return await agent_helpers.agent_names(FALLBACK_AGENTS=FALLBACK_AGENTS, icon_maps=icon_maps)


load_agents = state.load_agents


save_agents = state.save_agents


def matching_map_key(data, map_name):
    return agent_helpers.matching_map_key(data, map_name)


def assign_agent(map_name, user_id, agent):
    return agent_helpers.assign_agent(map_name, user_id, agent, load_agents=load_agents, matching_map_key=matching_map_key, save_agents=save_agents)


def current_week():
    return agent_helpers.current_week(load_season=load_season)


def resolve_map(text):
    return agent_helpers.resolve_map(text, current_week=current_week, load_season=load_season)


NO_MAP = "I couldn't work out the map. Pick one from the list that appears as you type, or check season.json."


async def agent_autocomplete(interaction: discord.Interaction, current: str):
    return await agent_helpers.agent_autocomplete(interaction, current, agent_names=agent_names, app_commands=app_commands)


async def lineup_card_file(map_name, week_label, slots):
    return await agent_helpers.lineup_card_file(map_name, week_label, slots, icon_img=icon_img, icon_maps=icon_maps, render_lineup_card=render_lineup_card)


playbook_service = PlaybookService(PLAYBOOK_FILE)


async def available_playbook_maps():
    return await playbook_helpers.available_playbook_maps(SETTINGS=SETTINGS)


def find_playbook_map(maps, map_name):
    return playbook_helpers.find_playbook_map(maps, map_name, playbook_service=playbook_service)


async def playbook_diagram_file(strategy):
    return await playbook_helpers.playbook_diagram_file(strategy, PlaybookDataError=PlaybookDataError, icon_img=icon_img, playbook_service=playbook_service, render_playbook_card=render_playbook_card, valorant_map_catalog=valorant_map_catalog)


async def playbook_strategy_file(strategy, page_text):
    return await playbook_helpers.playbook_strategy_file(strategy, page_text, playbook_diagram_file=playbook_diagram_file, render_strategy_card=render_strategy_card)


async def playbook_map_autocomplete(interaction: discord.Interaction, current: str):
    return await playbook_helpers.playbook_map_autocomplete(interaction, current, JsonStoreError=JsonStoreError, SETTINGS=SETTINGS, app_commands=app_commands, available_playbook_maps=available_playbook_maps)


def make_command_context() -> CommandContext:
    """Assemble the dependencies exposed to command Cogs."""
    return CommandContext(
        AFFINITY=AFFINITY,
        NO_MAP=NO_MAP,
        NO_PLAYER=NO_PLAYER,
        REGIONS=REGIONS,
        TEAM_NAME=TEAM_NAME,
        agent_autocomplete=agent_autocomplete,
        agent_names=agent_names,
        api=api,
        assign_agent=assign_agent,
        available_playbook_maps=available_playbook_maps,
        build_lineup_reminder=build_lineup_reminder,
        cache_store=cache_store,
        cached=cached,
        cached_api=cached_api,
        discord_display_name=discord_display_name,
        find_playbook_map=find_playbook_map,
        history=history,
        icon_img=icon_img,
        icon_maps=icon_maps,
        lineup_card_file=lineup_card_file,
        load_accounts=load_accounts,
        load_agents=load_agents,
        load_matchfeeds=load_matchfeeds,
        load_play_sessions=load_play_sessions,
        load_queue_schedules=load_queue_schedules,
        load_season=load_season,
        load_summaries=load_summaries,
        map_autocomplete=map_autocomplete,
        match_detail=match_detail,
        matching_map_key=matching_map_key,
        play_match_image=play_match_image,
        playbook_map_autocomplete=playbook_map_autocomplete,
        playbook_service=playbook_service,
        playbook_strategy_file=playbook_strategy_file,
        rank_change_image=rank_change_image,
        recent_scoreboard_view=recent_scoreboard_view,
        register_account=register_account,
        render_scoreboard=render_scoreboard,
        resolve_map=resolve_map,
        resolve_player=resolve_player,
        save_accounts=save_accounts,
        save_agents=save_agents,
        save_matchfeeds=save_matchfeeds,
        save_play_sessions=save_play_sessions,
        save_queue_schedules=save_queue_schedules,
        schedule_card_file=schedule_card_file,
        summarise=summarise,
        tree=tree,
        ts=ts,
        valorant_acts=valorant_acts,
    )


async def warm_icon_cache():
    try:
        await icon_maps()
    except Exception as exc:
        print(f"Could not warm icon cache: {exc}")
    else:
        client._icons_warmed = True


@client.event
async def on_ready():
    if not client._commands_synced:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        else:
            await tree.sync()
        client._commands_synced = True
    if not client._icons_warmed and (client._icon_warm_task is None or client._icon_warm_task.done()):
        client._icon_warm_task = asyncio.create_task(warm_icon_cache(), name="warm-icon-cache")
    print(f"Logged in as {client.user}")
    print("Team lookup:", f"ID {TEAM_ID}" if TEAM_ID else f"name {TEAM_NAME}#{TEAM_TAG}")


if __name__ == "__main__":
    client.run(TOKEN)
