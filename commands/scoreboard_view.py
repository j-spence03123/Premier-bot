"""Interactive Premier match scoreboard selector."""

import discord

from utils.formatting import parse_time


class ScoreboardView(discord.ui.View):
    """Dropdown under /results to open the full scoreboard of any listed match."""

    def __init__(self, matches, embed, render_scoreboard):
        super().__init__(timeout=900)
        self.render_scoreboard = render_scoreboard
        self.matches = matches
        self.embed = embed
        options = []
        for i, (_, s) in enumerate(matches[:25]):
            d = parse_time(s.get("started"))
            options.append(
                discord.SelectOption(
                    label=f"{'WIN' if s['won'] else 'LOSS'} {s['score']} on {s['map']}"[:100],
                    description=d.strftime("%d %b %H:%M UTC") if d else None,
                    value=str(i),
                )
            )
        options[0].default = True  # the latest match is shown first
        self.select = discord.ui.Select(placeholder="View a match scoreboard", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        idx = int(interaction.data["values"][0])
        filename = f"match{idx}.png"
        file = await self.render_scoreboard(self.matches[idx][1], filename)
        embed = self.embed.copy()
        embed.set_image(url=f"attachment://{filename}")
        for i, opt in enumerate(self.select.options):
            opt.default = i == idx  # keep the dropdown showing the chosen match
        # edit the original message in place instead of posting a new one
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)
