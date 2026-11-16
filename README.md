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

Both commands require server administrator permissions and a sheet shared as **Anyone with the link → Viewer** with downloads allowed.

### Lineup

Run `/importlineup sheet:<tab link> week:<week label or start date>`. Use column B for player names and columns C onward for maps. Put each map name above its agent picks. Blank rows above the map headings are fine.

Players can be identified by an exact Discord name or nickname, a Discord user ID, or a linked Riot ID. The bot reads the map for that week from `/schedule` and saves its picks. Reimporting replaces that week's picks. Use `/lineup week:` to view them.

### Playbook

Run `/importplaybook` without a link to see the template. Paste it into cell **A1** of a playbook tab, then run `/importplaybook sheet:<tab link>`.

```text
Playbook	Abyss	Attack	A Split
Description	Split A through main and mid.
Step	Smoke heaven before entering from main.
Step	Wait for the mid players before planting.
Utility	Save one smoke for the retake.
Assignment	Kevin	Smoke heaven and call the execute.
Link	https://example.com/reference
```

Each Playbook row starts a strategy under its map and side in `/playbook`. Identical strategies are skipped. To change an existing strategy, use `/createplaybook`.
