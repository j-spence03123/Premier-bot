"""Application settings loaded from the process environment or a local .env file."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv


REGIONS = ("eu", "na", "ap", "kr", "latam", "br")
DEFAULT_COMPETITIVE_MAPS = ("Abyss", "Bind", "Corrode", "Haven", "Lotus", "Summit", "Sunset")


@dataclass(frozen=True)
class Settings:
    discord_token: str
    henrik_api_key: str
    team_id: Optional[str]
    team_name: str
    team_tag: str
    roster: Tuple[str, ...]
    affinity: str
    guild_id: Optional[str]
    x_bearer: Optional[str]
    x_username: Optional[str]
    x_keyword: str
    api_base: str
    cache_file: Path
    queue_schedule_file: Path
    season_file: Path
    playbook_file: Path
    accounts_file: Path
    agents_file: Path
    play_sessions_file: Path
    matchfeeds_file: Path
    rankstates_file: Path
    weekly_recaps_file: Path
    clutches_file: Path
    update_notes_file: Path
    announced_updates_file: Path
    icon_dir: Path
    font_dir: Path
    groq_api_key: Optional[str]
    groq_model: str
    groq_recap_model: str
    anthropic_api_key: Optional[str]
    recap_provider: str
    claude_recap_model: str
    claude_recap_effort: str
    competitive_maps: Tuple[str, ...]


def load_settings(environ=None) -> Settings:
    """Read settings, reporting all missing required variables at once."""
    if environ is None:
        load_dotenv()
        environ = os.environ

    discord_token = (environ.get("DISCORD_TOKEN") or "").strip()
    henrik_api_key = (environ.get("HENRIK_API_KEY") or "").strip()
    missing = []
    if not discord_token:
        missing.append("DISCORD_TOKEN")
    if not henrik_api_key:
        missing.append("HENRIK_API_KEY")
    if missing:
        raise RuntimeError(
            "Missing required configuration: " + ", ".join(missing) + ". "
            "Set these in the process environment or in a local .env file."
        )

    return Settings(
        discord_token=discord_token,
        henrik_api_key=henrik_api_key,
        team_id=(environ.get("TEAM_ID") or "").strip() or None,
        team_name=(environ.get("TEAM_NAME") or "").strip(),
        team_tag=(environ.get("TEAM_TAG") or "").strip(),
        roster=tuple(
            entry.strip()
            for entry in (environ.get("ROSTER") or "").split(",")
            if entry.strip()
        ),
        affinity=(environ.get("AFFINITY") or "eu").strip().lower() or "eu",
        guild_id=(environ.get("GUILD_ID") or "").strip() or None,
        x_bearer=(environ.get("X_BEARER_TOKEN") or "").strip() or None,
        x_username=(environ.get("X_USERNAME") or "").strip() or None,
        x_keyword=(environ.get("X_KEYWORD") or "premier").strip().lower() or "premier",
        api_base="https://api.henrikdev.xyz",
        cache_file=Path("cache.json"),
        queue_schedule_file=Path("queue_schedule.json"),
        season_file=Path("season.json"),
        playbook_file=Path("playbooks.json"),
        accounts_file=Path("accounts.json"),
        agents_file=Path("agents.json"),
        play_sessions_file=Path("play_sessions.json"),
        matchfeeds_file=Path("matchfeeds.json"),
        rankstates_file=Path("rankstates.json"),
        weekly_recaps_file=Path("weekly_recaps.json"),
        clutches_file=Path("clutches.json"),
        update_notes_file=Path(__file__).resolve().parent / "UPDATES.md",
        announced_updates_file=Path("announced_updates.json"),
        icon_dir=Path("icons"),
        font_dir=Path(__file__).resolve().parent / "assets" / "fonts",
        groq_api_key=(environ.get("GROQ_API_KEY") or "").strip() or None,
        groq_model=(environ.get("GROQ_MODEL") or "qwen/qwen3.8-27b").strip(),
        groq_recap_model=(environ.get("GROQ_RECAP_MODEL") or "openai/gpt-oss-120b").strip(),
        anthropic_api_key=(environ.get("ANTHROPIC_API_KEY") or "").strip() or None,
        recap_provider=(environ.get("RECAP_PROVIDER") or "claude").strip().lower(),
        claude_recap_model=(environ.get("CLAUDE_RECAP_MODEL") or "claude-sonnet-5-5").strip(),
        claude_recap_effort=(environ.get("CLAUDE_RECAP_EFFORT") or "medium").strip().lower(),
        competitive_maps=tuple(name.strip() for name in (environ.get("COMPETITIVE_MAPS") or "").split(",")
                               if name.strip()) or DEFAULT_COMPETITIVE_MAPS,
    )


SETTINGS = load_settings()
