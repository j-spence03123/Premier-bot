"""Discord slash commands for playbooks."""
import discord
from discord import app_commands
from discord.ext import commands
from commands.context import CommandContext
from utils.recap_tones import TONE_LABELS

from commands import playbook_handlers
from commands.playbook_admin import PlaybookAdminView
from commands.playbook_views import PlaybookView
from services.json_store import JsonStoreError

class PlaybooksCog(commands.Cog):
    def __init__(self, runtime: CommandContext):
        self.runtime = runtime

    @app_commands.command(name='playbook', description='Browse strategies by map and side')
    @app_commands.describe(map_name='Optional map to open first')
    async def playbook(self, interaction: discord.Interaction, map_name: str=''):
        return await playbook_handlers.playbook(interaction, map_name, JsonStoreError=JsonStoreError, PlaybookView=PlaybookView, available_playbook_maps=self.runtime.available_playbook_maps, find_playbook_map=self.runtime.find_playbook_map, playbook_service=self.runtime.playbook_service, playbook_strategy_file=self.runtime.playbook_strategy_file)

    @app_commands.command(name='createplaybook', description='Create, edit or delete playbook strategies (administrators only)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(map_name='Optional map')
    async def createplaybook(self, interaction: discord.Interaction, map_name: str=''):
        return await playbook_handlers.createplaybook(interaction, map_name, JsonStoreError=JsonStoreError, PlaybookAdminView=PlaybookAdminView, available_playbook_maps=self.runtime.available_playbook_maps, find_playbook_map=self.runtime.find_playbook_map, playbook_service=self.runtime.playbook_service)

    @playbook.autocomplete("map_name")
    @createplaybook.autocomplete("map_name")
    async def playbook_map_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.runtime.playbook_map_autocomplete(interaction, current)
