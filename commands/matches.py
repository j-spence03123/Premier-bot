"""Discord slash commands for matches."""
import discord
from discord import app_commands
from discord.ext import commands
from commands.context import CommandContext
from utils.recap_tones import TONE_LABELS

from commands import matchfeed_commands
from commands import premier_handlers
from commands.scoreboard_view import ScoreboardView
from commands.recent import recent_command
from utils.formatting import parse_time

class MatchesCog(commands.Cog):
    def __init__(self, runtime: CommandContext):
        self.runtime = runtime

    @app_commands.command(name='results', description='Premier results from the past week')
    @app_commands.describe(days='How many days back (default 7)')
    async def results(self, interaction: discord.Interaction, days: int=7):
        return await premier_handlers.results(interaction, days, ScoreboardView=lambda matches, embed: ScoreboardView(matches, embed, self.runtime.render_scoreboard), TEAM_NAME=self.runtime.TEAM_NAME, history=self.runtime.history, load_summaries=self.runtime.load_summaries, parse_time=parse_time, render_scoreboard=self.runtime.render_scoreboard, ts=self.runtime.ts)

    @app_commands.command(name='mapresults', description='Results and player stats on a specific map')
    @app_commands.describe(map_name='e.g. Ascent', limit='How many recent matches to show (max 5)')
    async def mapresults(self, interaction: discord.Interaction, map_name: str, limit: int=3):
        return await premier_handlers.mapresults(interaction, map_name, limit, history=self.runtime.history, load_summaries=self.runtime.load_summaries, render_scoreboard=self.runtime.render_scoreboard)

    @app_commands.command(name='play', description='Start or stop tracking a Valorant queue session')
    @app_commands.describe(action='Start tracking or stop your active session', players='Optional queued players, as @mentions')
    @app_commands.choices(action=[app_commands.Choice(name='Start', value='start'), app_commands.Choice(name='Stop', value='stop')])
    async def play_cmd(self, interaction: discord.Interaction, action: app_commands.Choice[str], players: str=''):
        return await matchfeed_commands.play_cmd(interaction, action, players, load_accounts=self.runtime.load_accounts, load_play_sessions=self.runtime.load_play_sessions, save_play_sessions=self.runtime.save_play_sessions)

    @app_commands.command(name='matchfeed', description="Set this server's automatic Valorant match and rank report channel")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel='Channel for match reports; leave blank to disable')
    async def matchfeed_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
        return await matchfeed_commands.matchfeed_cmd(interaction, channel, load_matchfeeds=self.runtime.load_matchfeeds, save_matchfeeds=self.runtime.save_matchfeeds)

    @app_commands.command(name='matchfeed_tone', description="Set the tone of this server's matchfeed recaps")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(tone='How the matchfeed recap should describe performances')
    @app_commands.choices(tone=[app_commands.Choice(name=label, value=value) for value, label in TONE_LABELS.items()])
    async def matchfeed_tone_cmd(self, interaction: discord.Interaction, tone: app_commands.Choice[str]):
        return await matchfeed_commands.matchfeed_tone_cmd(interaction, tone, load_matchfeeds=self.runtime.load_matchfeeds, save_matchfeeds=self.runtime.save_matchfeeds)

    @app_commands.command(name='recent', description="Show a player's most recent competitive match scoreboard")
    @app_commands.describe(player='Mention a member with a linked account (defaults to you)')
    async def recent_cmd(self, interaction: discord.Interaction, player: discord.Member=None):
        return await recent_command(interaction, player, load_accounts=self.runtime.load_accounts, affinity=self.runtime.AFFINITY, cached_api=self.runtime.cached_api, cached=self.runtime.cached, match_detail=self.runtime.match_detail, recent_scoreboard_view=self.runtime.recent_scoreboard_view)

    @mapresults.autocomplete("map_name")
    async def map_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.runtime.map_autocomplete(interaction, current)
