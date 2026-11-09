"""Discord slash commands for administration."""
import discord
from discord import app_commands
from discord.ext import commands
from commands.context import CommandContext
from utils.recap_tones import TONE_LABELS

from commands import admin_handlers
from commands import premier_handlers
from graphics.help_card import render_help_card

class AdministrationCog(commands.Cog):
    def __init__(self, runtime: CommandContext):
        self.runtime = runtime

    @app_commands.command(name='clearcache', description='Force fresh data on the next command')
    @app_commands.default_permissions(manage_guild=True)
    async def clearcache(self, interaction: discord.Interaction):
        return await admin_handlers.clearcache(interaction, cache_store=self.runtime.cache_store)

    @app_commands.command(name='testreminder', description='Post a test queue reminder showing agent picks and mentioning picked players (administrators only)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel='Where to post the test reminder (defaults to the configured reminder channel)')
    async def testreminder(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
        return await premier_handlers.testreminder(interaction, channel, build_lineup_reminder=self.runtime.build_lineup_reminder, load_queue_schedules=self.runtime.load_queue_schedules)

    @app_commands.command(name='testplaycard', description='Preview a sample play-session match card (administrators only)')
    @app_commands.default_permissions(administrator=True)
    async def test_play_card(self, interaction: discord.Interaction):
        return await admin_handlers.test_play_card(interaction, play_match_image=self.runtime.play_match_image)

    @app_commands.command(name='testrankcard', description='Preview a rank change image (administrators only)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(scenario='Choose a subrank promotion, full-rank promotion, or derank preview')
    @app_commands.choices(scenario=[app_commands.Choice(name='Subrank promotion: Platinum 1 → Platinum 2', value='subrank'), app_commands.Choice(name='Full promotion: Platinum 3 → Diamond 1', value='promotion'), app_commands.Choice(name='Derank: Diamond 1 → Platinum 3', value='derank')])
    async def test_rank_card(self, interaction: discord.Interaction, scenario: app_commands.Choice[str]):
        return await admin_handlers.test_rank_card(interaction, scenario, rank_change_image=self.runtime.rank_change_image)

    @app_commands.command(name='help', description='List all commands')
    async def help_cmd(self, interaction: discord.Interaction):
        return await admin_handlers.help_cmd(interaction, HELP_SECTIONS=admin_handlers.HELP_SECTIONS, render_help_card=render_help_card, tree=self.runtime.tree)

    @app_commands.command(name='debug', description='Dump raw API data (to check field names)')
    @app_commands.choices(what=[app_commands.Choice(name='schedule', value='schedule'), app_commands.Choice(name='history', value='history')])
    async def debug(self, interaction: discord.Interaction, what: app_commands.Choice[str]):
        return await admin_handlers.debug(interaction, what, AFFINITY=self.runtime.AFFINITY, cached_api=self.runtime.cached_api, history=self.runtime.history)
