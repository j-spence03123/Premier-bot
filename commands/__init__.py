"""Register the bot's feature Cogs."""

from .administration import AdministrationCog
from .agents import AgentsCog
from .matches import MatchesCog
from .players import PlayersCog
from .playbooks import PlaybooksCog
from .premier import PremierCog
from .context import CommandContext

COG_TYPES = (PremierCog, MatchesCog, PlayersCog, AgentsCog, PlaybooksCog, AdministrationCog)


async def install_command_cogs(bot, runtime: CommandContext):
    for cog_type in COG_TYPES:
        await bot.add_cog(cog_type(runtime))
