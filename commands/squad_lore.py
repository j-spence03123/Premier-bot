"""Manage the optional callbacks used by a server's matchfeed."""

import discord

from services.squad_lore import MAX_ENTRIES, TRIGGERS


async def _feed(interaction, load_matchfeeds):
    if not interaction.guild or not interaction.permissions.administrator:
        await interaction.response.send_message("Only server administrators can manage squad lore.", ephemeral=True)
        return None
    feeds = load_matchfeeds()
    if str(interaction.guild_id) not in feeds:
        await interaction.response.send_message("Set up a match feed with /matchfeed first.", ephemeral=True)
        return None
    return feeds


async def set_entry(interaction, label, trigger, player, map_name, nickname, *, load_matchfeeds, save_matchfeeds):
    feeds = await _feed(interaction, load_matchfeeds)
    if feeds is None:
        return
    label = " ".join(label.split())
    map_name = " ".join((map_name or "").split())
    if not label or len(label) > 48 or len(map_name) > 40:
        return await interaction.response.send_message(
            "Use a label of 1–48 characters and a map name of up to 40 characters.", ephemeral=True,
        )
    if trigger not in TRIGGERS or (nickname and player is None):
        return await interaction.response.send_message("Choose a trigger and select a player for a nickname.", ephemeral=True)
    if player and trigger in ("clutch_win", "thrifty_win"):
        return await interaction.response.send_message(
            "Clutch and thrifty wins are team triggers. Leave the player blank.", ephemeral=True,
        )
    entries = feeds[str(interaction.guild_id)].setdefault("squad_lore", {})
    key = label.casefold()
    if key not in entries and len(entries) >= MAX_ENTRIES:
        return await interaction.response.send_message(
            f"This server has {MAX_ENTRIES} entries. Remove one before adding another.", ephemeral=True,
        )
    entries[key] = {
        "label": label, "kind": "nickname" if nickname else "inside joke", "trigger": trigger,
        "member_id": str(player.id) if player else None, "map": map_name or None,
    }
    save_matchfeeds(feeds)
    await interaction.response.send_message(
        f"Saved **{discord.utils.escape_markdown(label)}** for **{TRIGGERS[trigger]}**.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
    )


async def list_entries(interaction, *, load_matchfeeds):
    feeds = await _feed(interaction, load_matchfeeds)
    if feeds is None:
        return
    entries = feeds[str(interaction.guild_id)].get("squad_lore") or {}
    if not entries:
        return await interaction.response.send_message("No squad lore saved. Add some with /squadlore set.", ephemeral=True)
    embed = discord.Embed(title="Squad lore")
    for entry in entries.values():
        detail = [entry["kind"].capitalize(), TRIGGERS[entry["trigger"]]]
        if entry.get("member_id"):
            detail.append(f"<@{entry['member_id']}>")
        if entry.get("map"):
            detail.append(discord.utils.escape_markdown(entry["map"]))
        embed.add_field(name=discord.utils.escape_markdown(entry["label"]), value=" · ".join(detail), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def remove_entry(interaction, label, *, load_matchfeeds, save_matchfeeds):
    feeds = await _feed(interaction, load_matchfeeds)
    if feeds is None:
        return
    entries = feeds[str(interaction.guild_id)].get("squad_lore") or {}
    removed = entries.pop(" ".join(label.split()).casefold(), None)
    if not removed:
        return await interaction.response.send_message("No entry with that label. See /squadlore list.", ephemeral=True)
    save_matchfeeds(feeds)
    await interaction.response.send_message(
        f"Removed **{discord.utils.escape_markdown(removed['label'])}**.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
    )
