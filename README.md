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

## Import lineups and playbooks from Google Sheets

Server administrators can run `/importsheet` without a link to see the template. Paste it into cell **A1** in Google Sheets, set sharing to **Anyone with the link → Viewer** with downloads allowed, then paste that tab's link into `/importsheet sheet:`.

```text
Lineup	Week 6
Pick	Kevin#1234	Omen
Pick	Spam#5678	Cypher
Playbook	Abyss	Attack	A Split
Description	Split A through main and mid.
Step	Smoke heaven before entering from main.
Step	Wait for the mid players before planting.
Utility	Save one smoke for the retake.
Assignment	Kevin	Smoke heaven and call the execute.
Link	https://example.com/reference
```

- Use a week label or start date from `/schedule`. Identify players by a Riot ID linked through `/register` or by their Discord user ID.
- Each lineup section sets the picks for that week. Open it with `/lineup week:`, or run `/lineup` when that week is current.
- A playbook section creates one strategy under its map and side in `/playbook`. Identical strategies are skipped. To change a strategy with the same name, use `/createplaybook`.
- The bot reads the linked tab when you run the import. Run it again to apply later edits to a lineup.
