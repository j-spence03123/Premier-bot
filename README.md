# Premier Bot

A Python Discord bot for VALORANT Premier schedules, player statistics, match scoreboards, playbooks, and automatic match and rank updates, including optional AI-generated recaps.

## Dependencies

- Python 3.10+
- `discord.py` >= 2.7
- `aiohttp` >= 3.9
- `python-dotenv` >= 1.0
- `Pillow` >= 10.1
- `tzdata` >= 2024.1

All Python packages are listed in `requirements.txt`. A Discord bot token and HenrikDev API key are required; a Groq API key is optional for AI recaps.

## Run

From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Fill in `DISCORD_TOKEN` and `HENRIK_API_KEY` in `.env`. Optionally set `GROQ_API_KEY` for AI recaps and configure your team settings.

```bash
python bot.py
```

On Ubuntu, install `python3-venv` if needed. Install `fonts-dejavu-core` for image-rendering font support.
