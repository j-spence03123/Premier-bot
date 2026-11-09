"""Feature command implementations; application dependencies are injected at registration."""
from __future__ import annotations
import discord

async def playbook(interaction, map_name='', *, JsonStoreError, PlaybookView, available_playbook_maps, find_playbook_map, playbook_service, playbook_strategy_file):
    await interaction.response.defer()
    try:
        maps = await available_playbook_maps()
        picked = find_playbook_map(maps, map_name)
        if map_name and (not picked):
            return await interaction.followup.send('Map not found. Choose a map from the menu.', ephemeral=True)
        view = PlaybookView(playbook_service, maps, interaction.user.id, picked, playbook_strategy_file)
        view.message = await interaction.followup.send(embed=view.embed(), view=view, allowed_mentions=discord.AllowedMentions.none(), wait=True)
    except JsonStoreError as exc:
        await interaction.followup.send(f'Playbook unavailable: {exc}', ephemeral=True)

async def createplaybook(interaction, map_name='', *, JsonStoreError, PlaybookAdminView, available_playbook_maps, find_playbook_map, playbook_service):
    if not interaction.guild or not interaction.permissions.administrator:
        return await interaction.response.send_message('Only server administrators can use this command.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        maps = await available_playbook_maps()
        picked = find_playbook_map(maps, map_name)
        if map_name and (not picked):
            return await interaction.followup.send('Map not found. Choose a map from the menu.', ephemeral=True)
        view = PlaybookAdminView(playbook_service, maps, interaction.user.id, picked)
        view.message = await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), wait=True)
    except JsonStoreError as exc:
        await interaction.followup.send(f'Playbook unavailable: {exc}', ephemeral=True)
