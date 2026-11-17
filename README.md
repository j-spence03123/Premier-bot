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

Automatic matchfeeds also post a session recap after an hour without a new completed match for the same lineup. The regular two-minute poll checks for new games before closing sessions. Recaps show the session record, maps, each player's net RR, and a short AI summary with standout plays. Missing RR is retried before posting and shown as unavailable when any game is still missing. AI summaries use the existing Groq configuration and server tone, with factual highlights as a fallback. Each lineup and solo player has its own session. Match history cannot identify a game still in progress.

Session details are saved with matchfeed state and survive restarts. Recap tracking starts with the first match detected after this feature is installed. The recap card uses the bot's existing Pillow image generation and shared match-card fonts.

After linking a main account with `/register`, use `/registersmurf riot_id:Name#Tag` to link up to two alternate accounts. They appear in the matchfeed under the same Discord user. `/rank`, `/player`, and `/recent` let you select **Smurf 1** or **Smurf 2**. Use `/accounts` to see your links and `/unregister riot_id:Name#Tag` to remove a smurf.

Server administrators can add `member:@Player` to `/registersmurf` to register for someone else.

## Import lineups and playbooks from Google Sheets

Both commands require server administrator permissions and a sheet shared as **Anyone with the link → Viewer** with downloads allowed.

### Lineup

Run `/importlineup sheet:<tab link>`. Use column B for player names and columns C onward for maps. Put each map name above its agent picks. Blank rows above the map headings are fine.

Players can be identified by an exact Discord name or nickname, a Discord user ID, or a linked Riot ID. The bot matches map columns to every week in `/schedule`. Reimporting replaces picks for matching weeks. Weeks without a matching column keep their existing picks. Use `/lineup week:` to view them.

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
