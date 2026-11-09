"""Discord slash commands for players."""
import discord
from discord import app_commands
from discord.ext import commands
from commands.context import CommandContext
from utils.recap_tones import TONE_LABELS

from commands import player_handlers
from graphics.player_history import render_player_history
from utils.stored_matches import parse_stored

class PlayersCog(commands.Cog):
    def __init__(self, runtime: CommandContext):
        self.runtime = runtime

    @app_commands.command(name='register', description='Link your Valorant account to your Discord user')
    @app_commands.describe(riot_id='Your Riot ID, like Name#TAG', region="eu, na, ap, kr, latam or br (default: your team's)")
    async def register(self, interaction: discord.Interaction, riot_id: str, region: str=''):
        return await player_handlers.register(interaction, riot_id, region, register_account=self.runtime.register_account)

    @app_commands.command(name='registeruser', description='Link a Valorant account to another server member (administrators only)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member='Server member to register', riot_id='Riot ID, like Name#TAG', region="eu, na, ap, kr, latam or br (default: your team's)")
    async def register_user(self, interaction: discord.Interaction, member: discord.Member, riot_id: str, region: str=''):
        return await player_handlers.register_user(interaction, member, riot_id, region, register_account=self.runtime.register_account)

    @app_commands.command(name='unregister', description='Remove your linked Valorant account')
    async def unregister(self, interaction: discord.Interaction):
        return await player_handlers.unregister(interaction, load_accounts=self.runtime.load_accounts, save_accounts=self.runtime.save_accounts)

    @app_commands.command(name='accounts', description='Show registered Valorant accounts')
    async def accounts_cmd(self, interaction: discord.Interaction):
        return await player_handlers.accounts_cmd(interaction, load_accounts=self.runtime.load_accounts)

    @app_commands.command(name='rank', description='Current and peak rank for a Riot ID, you, or a member with a linked account')
    @app_commands.describe(name='Riot name, or Name#TAG', tag='Tag (after the #)', region='eu, na, ap, kr, latam or br', member='Select or @mention a member; uses their /register account')
    async def rank_cmd(self, interaction: discord.Interaction, name: str='', tag: str='', region: str='', member: discord.Member=None):
        return await player_handlers.rank_cmd(interaction, name, tag, region, member, AFFINITY=self.runtime.AFFINITY, NO_PLAYER=self.runtime.NO_PLAYER, REGIONS=self.runtime.REGIONS, cached_api=self.runtime.cached_api, icon_maps=self.runtime.icon_maps, load_accounts=self.runtime.load_accounts, resolve_player=self.runtime.resolve_player)

    @app_commands.command(name='player', description='Recent matches and averages for a Riot ID, you, or a member with a linked account')
    @app_commands.describe(name='Riot name, or Name#TAG', tag='Tag (after the #)', mode='Game mode (default competitive)', region='eu, na, ap, kr, latam or br', member='Select or @mention a member; uses their /register account')
    @app_commands.choices(mode=[app_commands.Choice(name='Competitive', value='competitive'), app_commands.Choice(name='Unrated', value='unrated'), app_commands.Choice(name='Premier', value='premier')])
    async def player_cmd(self, interaction: discord.Interaction, name: str='', tag: str='', mode: app_commands.Choice[str]=None, region: str='', member: discord.Member=None):
        return await player_handlers.player_cmd(interaction, name, tag, mode, region, member, AFFINITY=self.runtime.AFFINITY, NO_PLAYER=self.runtime.NO_PLAYER, REGIONS=self.runtime.REGIONS, cached_api=self.runtime.cached_api, icon_img=self.runtime.icon_img, icon_maps=self.runtime.icon_maps, load_accounts=self.runtime.load_accounts, parse_stored=parse_stored, render_player_history=render_player_history, resolve_player=self.runtime.resolve_player)
