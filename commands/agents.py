"""Discord slash commands for agents."""
import discord
from discord import app_commands
from discord.ext import commands
from commands.context import CommandContext
from utils.recap_tones import TONE_LABELS

from commands import agent_handlers
from utils.formatting import fmt_range

class AgentsCog(commands.Cog):
    def __init__(self, runtime: CommandContext):
        self.runtime = runtime

    @app_commands.command(name='agent', description='Pick your agent for a Premier map')
    @app_commands.describe(agent_name="The agent you'll play", map_name='Map (default: the current or next map)')
    async def agent_cmd(self, interaction: discord.Interaction, agent_name: str, map_name: str=''):
        return await agent_handlers.agent_cmd(interaction, agent_name, map_name, NO_MAP=self.runtime.NO_MAP, agent_names=self.runtime.agent_names, assign_agent=self.runtime.assign_agent, resolve_map=self.runtime.resolve_map)

    @app_commands.command(name='assignagent', description='Assign an agent to a player (administrators only)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user='Player to assign', agent_name='Agent to assign', map_name='Map (default: the current or next map)')
    async def assignagent(self, interaction: discord.Interaction, user: discord.Member, agent_name: str, map_name: str=''):
        return await agent_handlers.assignagent(interaction, user, agent_name, map_name, NO_MAP=self.runtime.NO_MAP, agent_names=self.runtime.agent_names, assign_agent=self.runtime.assign_agent, resolve_map=self.runtime.resolve_map)

    @app_commands.command(name='lineup', description='See the team lineup and agent icons for a map')
    @app_commands.describe(map_name='Map (default: the current or next map)')
    async def lineup(self, interaction: discord.Interaction, map_name: str=''):
        return await agent_handlers.lineup(interaction, map_name, NO_MAP=self.runtime.NO_MAP, discord_display_name=self.runtime.discord_display_name, fmt_range=fmt_range, lineup_card_file=self.runtime.lineup_card_file, load_agents=self.runtime.load_agents, load_season=self.runtime.load_season, matching_map_key=self.runtime.matching_map_key, resolve_map=self.runtime.resolve_map)

    @app_commands.command(name='clearagent', description='Remove your agent pick for a map')
    @app_commands.describe(map_name='Map (default: the current or next map)')
    async def clearagent(self, interaction: discord.Interaction, map_name: str=''):
        return await agent_handlers.clearagent(interaction, map_name, NO_MAP=self.runtime.NO_MAP, load_agents=self.runtime.load_agents, resolve_map=self.runtime.resolve_map, save_agents=self.runtime.save_agents)

    @agent_cmd.autocomplete("agent_name")
    @assignagent.autocomplete("agent_name")
    async def agent_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.runtime.agent_autocomplete(interaction, current)

    @agent_cmd.autocomplete("map_name")
    @assignagent.autocomplete("map_name")
    @lineup.autocomplete("map_name")
    @clearagent.autocomplete("map_name")
    async def map_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.runtime.map_autocomplete(interaction, current)
