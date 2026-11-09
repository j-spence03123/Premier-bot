"""Explicit application services provided to Discord command Cogs."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from discord import app_commands
from services.cache import JsonCache
from services.playbook_service import PlaybookService


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Dependencies used by command handlers and their autocomplete callbacks."""
    AFFINITY: str
    NO_MAP: str
    NO_PLAYER: str
    REGIONS: Collection[str]
    TEAM_NAME: str
    agent_autocomplete: Callable[..., Any]
    agent_names: Callable[..., Any]
    api: Callable[..., Any]
    assign_agent: Callable[..., Any]
    available_playbook_maps: Callable[..., Any]
    build_lineup_reminder: Callable[..., Any]
    cache_store: JsonCache
    cached: Callable[..., Any]
    cached_api: Callable[..., Any]
    discord_display_name: Callable[..., Any]
    find_playbook_map: Callable[..., Any]
    history: Callable[..., Any]
    icon_img: Callable[..., Any]
    icon_maps: Callable[..., Any]
    lineup_card_file: Callable[..., Any]
    load_accounts: Callable[..., Any]
    load_agents: Callable[..., Any]
    load_matchfeeds: Callable[..., Any]
    load_play_sessions: Callable[..., Any]
    load_queue_schedules: Callable[..., Any]
    load_season: Callable[..., Any]
    load_summaries: Callable[..., Any]
    map_autocomplete: Callable[..., Any]
    match_detail: Callable[..., Any]
    matching_map_key: Callable[..., Any]
    play_match_image: Callable[..., Any]
    playbook_map_autocomplete: Callable[..., Any]
    playbook_service: PlaybookService
    playbook_strategy_file: Callable[..., Any]
    rank_change_image: Callable[..., Any]
    recent_scoreboard_view: Callable[..., Any]
    register_account: Callable[..., Any]
    render_scoreboard: Callable[..., Any]
    resolve_map: Callable[..., Any]
    resolve_player: Callable[..., Any]
    save_accounts: Callable[..., Any]
    save_agents: Callable[..., Any]
    save_matchfeeds: Callable[..., Any]
    save_play_sessions: Callable[..., Any]
    save_queue_schedules: Callable[..., Any]
    schedule_card_file: Callable[..., Any]
    summarise: Callable[..., Any]
    tree: app_commands.CommandTree
    ts: Callable[..., Any]
    valorant_acts: Callable[..., Any]
