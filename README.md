# Premier Bot

A Discord bot that tracks a VALORANT squad: auto-posted match cards, rank changes, Premier schedules and AI recaps.

![Match feed card](docs/images/match-feed.png)

## Features

- **Match feed**: posts a card after every squad game, with per-player tags and an optional AI recap.
- **Rank tracking**: rank-up and derank cards for linked players.
- **Player stats**: `/rank`, `/player` history, and `/recent` scoreboards with a round-by-round strip.
- **Premier tools**: `/schedule`, `/results`, `/mapresults`, `/scout` an opposing team, and `/lineup`.
- **Playbooks**: browse strategies by map and side; import playbooks and lineups from Google Sheets.
- **Sessions and recaps**: `/play` queue sessions, weekly recaps, scheduled queue reminders.
- **Account linking**: link a main account plus up to two smurfs per member.

Run `/help` in Discord for the full command list.

## Install and run

You need Python 3.10+, a Discord bot token and a [HenrikDev](https://docs.henrikdev.xyz) API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then fill in DISCORD_TOKEN and HENRIK_API_KEY
python bot.py
```

Development checks (same as CI):

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

## Environment variables

Set these in `.env` or the process environment. See `.env.example`.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DISCORD_TOKEN` | yes | | Discord bot token |
| `HENRIK_API_KEY` | yes | | HenrikDev VALORANT API key |
| `TEAM_ID` | | | Premier team ID; takes precedence over name/tag |
| `TEAM_NAME`, `TEAM_TAG` | | | Premier team lookup by name and tag |
| `ROSTER` | | | Comma-separated Riot IDs, e.g. `PlayerOne#EU,PlayerTwo#EU` |
| `AFFINITY` | | `eu` | Region: `eu`, `na`, `ap`, `kr`, `latam`, `br` |
| `COMPETITIVE_MAPS` | | `Abyss,Bind,Corrode,Haven,Lotus,Summit,Sunset` | Map pool for playbook menus |
| `GUILD_ID` | | | Sync commands to one server instead of globally |
| `GROQ_API_KEY` | | | Enables AI recaps |
| `GROQ_MODEL` | | `qwen/qwen3.8-27b` | Model for weekly summaries |
| `GROQ_RECAP_MODEL` | | `openai/gpt-oss-120b` | Model for match feed recaps |
| `X_BEARER_TOKEN`, `X_USERNAME` | | | Optional X API schedule lookup |
| `X_KEYWORD` | | `premier` | Keyword for the X schedule lookup |

## Folder structure

```
bot.py          Entry point: Discord client, command registration, startup
config.py       Settings loaded from the environment / .env
commands/       Slash commands and their handlers and views
services/       HenrikDev API, match feed, recaps, storage, background tasks
graphics/       Pillow-rendered cards (match, rank, scoreboard, lineup, recaps)
utils/          Formatting, stats, Riot ID parsing, schedules
models/         Data models (playbooks)
assets/fonts/   Bundled Roboto, Lora and Noto Sans SC fonts (SIL OFL 1.1)
docs/images/    README screenshots
tests/          pytest suite
```

Runtime state (`accounts.json`, `cache.json`, `matchfeeds.json`, …) is written to the working directory and is git-ignored.
