"""Discord slash commands for premier."""
import discord
from discord import app_commands
from discord.ext import commands
from commands.context import CommandContext
from utils.recap_tones import TONE_LABELS

from commands import premier_handlers
from utils.premier_seasons import extract_premier_seasons
from utils.formatting import parse_time
import time

class PremierCog(commands.Cog):
    def __init__(self, runtime: CommandContext):
        self.runtime = runtime

    @app_commands.command(name='schedule', description='View the Premier map schedule')
    async def schedule(self, interaction: discord.Interaction):
        return await premier_handlers.schedule(interaction, load_season=self.runtime.load_season, schedule_card_file=self.runtime.schedule_card_file)

    @app_commands.command(name='setschedule', description='Set weekly queue reminder days and times')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(days='Queue days, comma-separated (e.g. Tuesday,Thursday)', local_time='Queue start time in 24-hour HH:MM format', timezone_name='IANA time zone (e.g. Europe/London or America/Los_Angeles)', channel='Channel for reminders (defaults to this channel)')
    async def setschedule(self, interaction: discord.Interaction, days: str='', local_time: str='', timezone_name: str='', channel: discord.TextChannel=None):
        return await premier_handlers.setschedule(interaction, days, local_time, timezone_name, channel, load_queue_schedules=self.runtime.load_queue_schedules, save_queue_schedules=self.runtime.save_queue_schedules)

    @app_commands.command(name='findteam', description="Find your team ID from a player's Riot ID")
    @app_commands.describe(riot_name='Riot name (before the #)', riot_tag='Tag (after the #)')
    async def findteam(self, interaction: discord.Interaction, riot_name: str, riot_tag: str):
        return await premier_handlers.findteam(interaction, riot_name, riot_tag, AFFINITY=self.runtime.AFFINITY, api=self.runtime.api)

    @app_commands.command(name='scout', description='Scout a Premier team’s win rate and agent picks across VALORANT acts')
    @app_commands.describe(team_name='Premier team name', team_tag='Premier team tag', acts='How many recent VALORANT acts to include (default: 1)')
    async def scout(self, interaction: discord.Interaction, team_name: str, team_tag: str, acts: app_commands.Range[int, 1, 10]=1):
        return await premier_handlers.scout(interaction, team_name, team_tag, acts, AFFINITY=self.runtime.AFFINITY, api=self.runtime.api, cache_store=self.runtime.cache_store, cached=self.runtime.cached, cached_api=self.runtime.cached_api, extract_premier_seasons=extract_premier_seasons, match_detail=self.runtime.match_detail, parse_time=parse_time, summarise=self.runtime.summarise, time=time, valorant_acts=self.runtime.valorant_acts)
