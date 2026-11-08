# Premier Bot

A Discord bot for VALORANT Premier schedules, match scoreboards, playbooks, player stats, and automatic match and rank updates.

## Setup

Requires Python 3.10 or newer, a Discord bot token, and a HenrikDev API key. Python dependencies are listed in `requirements.txt` and installed below.

```bash
# Ubuntu: install Python's virtual environment support
sudo apt-get install python3-venv fonts-dejavu-core

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `DISCORD_TOKEN` and `HENRIK_API_KEY`. Set `GROQ_API_KEY` if you want AI match recaps.

Start the bot from the repository directory:

```bash
python bot.py
```
