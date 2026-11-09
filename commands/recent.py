"""Recent-match command and interactive scoreboard."""

import asyncio
from urllib.parse import quote

import discord

from graphics.recent_scoreboard import render_recent_scoreboard
from utils.recent_scoreboard import has_half_data


class RecentScoreboardView(discord.ui.View):
    """Switch match periods using the match data already loaded for the message."""

    def __init__(self, detail, target, map_path, agent_icons, rank_icons):
        super().__init__(timeout=900)
        self.detail, self.target, self.map_path = detail, target, map_path
        self.agent_icons, self.rank_icons = agent_icons, rank_icons
        if not has_half_data(detail):
            self.first.disabled = True
            self.second.disabled = True

    async def card(self, period):
        loop = asyncio.get_running_loop()
        buffer = await loop.run_in_executor(None, render_recent_scoreboard, self.detail, self.target,
                                            period, self.map_path, self.agent_icons, self.rank_icons)
        return discord.File(buffer, filename="scoreboard.png")

    async def switch(self, interaction, period):
        await interaction.response.defer()
        card = await self.card(period)
        await interaction.edit_original_response(attachments=[card], view=self)

    @discord.ui.button(label="Full match", style=discord.ButtonStyle.secondary)
    async def full(self, interaction, button):
        await self.switch(interaction, "full")

    @discord.ui.button(label="First half", style=discord.ButtonStyle.secondary)
    async def first(self, interaction, button):
        await self.switch(interaction, "first")

    @discord.ui.button(label="Second half + OT", style=discord.ButtonStyle.secondary)
    async def second(self, interaction, button):
        await self.switch(interaction, "second")


async def recent_scoreboard_view(detail, target, *, map_background_path, icon_maps, icon_img):
    map_data = (detail.get("metadata") or {}).get("map") or {}
    map_id = map_data.get("id") or map_data.get("uuid")
    path = await map_background_path(map_id, map_data.get("name", "Unknown")) if map_id else None
    try:
        catalog = await icon_maps()
    except Exception as exc:
        print(f"Recent scoreboard icon catalog unavailable: {exc}")
        catalog = {}
    by_name = {name.casefold(): agent_id for agent_id, name in catalog.get("agent_names", {}).items()}
    agent_urls = {}
    tier_urls = {}
    for player in detail.get("players") or []:
        agent = player.get("agent") or {}
        agent_id = str(agent.get("id") or agent.get("uuid") or by_name.get(str(agent.get("name") or "").casefold()) or "").lower()
        if agent_id and player.get("puuid"):
            agent_urls[player["puuid"]] = catalog.get("agents", {}).get(agent_id) or f"https://media.valorant-api.com/agents/{agent_id}/displayicon.png"
        tier_id = str((player.get("tier") or {}).get("id") or "")
        if tier_id and catalog.get("tiers", {}).get(tier_id):
            tier_urls[tier_id] = catalog["tiers"][tier_id]
    agent_images, tier_images = await asyncio.gather(
        asyncio.gather(*(icon_img(url, 55) for url in agent_urls.values())),
        asyncio.gather(*(icon_img(url, 40) for url in tier_urls.values())),
    )
    return RecentScoreboardView(detail, target, path, dict(zip(agent_urls, agent_images)),
                                dict(zip(tier_urls, tier_images)))


async def recent_command(interaction, player, *, load_accounts, affinity, cached_api, cached, match_detail, recent_scoreboard_view):
    target = player or interaction.user
    accounts = load_accounts()
    account = accounts.get(str(target.id))
    if not account:
        return await interaction.response.send_message(
            f"{getattr(target, 'display_name', target.name)} needs to link a VALORANT account with /register first.",
            ephemeral=True,
        )
    await interaction.response.defer()
    region = account.get("region") or affinity
    try:
        history = await cached_api(
            f"/valorant/v1/stored-matches/{region}/{quote(account['name'])}/{quote(account['tag'])}",
            120, mode="competitive", size=10,
        )
        matches = [m for m in history or [] if (m.get("meta") or {}).get("id")]
        matches.sort(key=lambda m: (m.get("meta") or {}).get("started_at") or "", reverse=True)
        if not matches:
            return await interaction.followup.send(f"No completed competitive matches found for {account['name']}#{account['tag']}.")
        latest = matches[0]
        meta = latest.get("meta") or {}
        match_id = meta["id"]
        detail = await cached(
            f"recentmatch:{region}:{match_id}", None,
            lambda: match_detail(match_id, region),
        )
        player_stats = latest.get("stats") or {}
        puuid = player_stats.get("puuid")
        participants = detail.get("players", [])
        target_player = next((p for p in participants if puuid and p.get("puuid") == puuid), None)
        if not target_player:
            wanted = f"{account['name']}#{account['tag']}".casefold()
            target_player = next((p for p in participants
                                  if f"{p.get('name', '')}#{p.get('tag', '')}".casefold() == wanted), None)
        if not target_player:
            return await interaction.followup.send("I found the match, but couldn't match the linked account to its scoreboard.")
        view = await recent_scoreboard_view(detail, target_player)
        card = await view.card("full")
        await interaction.followup.send(file=card, view=view, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        await interaction.followup.send(f"Couldn't load the recent match: {str(exc)[:300]}")
