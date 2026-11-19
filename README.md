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

## Squad lore

With an automatic matchfeed configured, server admins can use `/squadlore set` to save a nickname or inside joke.
Choose a match trigger and optionally restrict it to a map or linked Discord member.
Use `/squadlore list` to review entries and `/squadlore remove` to delete one.
AI recaps can use one matching callback when it fits the server's tone. A posted callback is followed by at least
three reports without a saved callback, and the same entry needs at least six reports in between.
The bot also tracks recorded games together and map streaks for each lineup of linked members from the first match
posted after the update.

## Weekly recap

With an automatic matchfeed configured, the bot posts a weekly recap card in the matchfeed channel every Sunday at
20:00 UK time, covering Sunday 20:00 to Sunday 20:00. It shows each registered player's RR gain or loss, the top three
competitive games of the week, rank ups and deranks, the Premier team's results (left out when no Premier games were played) and a
short summary (AI-written when `GROQ_API_KEY` is set). Administrators can preview the week so far with `/weeklyrecap`.
