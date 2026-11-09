from utils.match_summary import _play_headline, _play_recap
from utils.recap_tones import DEFAULT_TONE
from io import BytesIO
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

import pytest


def test_registered_only_fallback_mentions_only_the_selected_player():
    registered = {"puuid": "p1", "name": "Friend", "team_id": "Red",
                  "stats": {"score": 2100, "kills": 10, "deaths": 12, "assists": 2}}
    other = {"puuid": "p2", "name": "Stranger", "team_id": "Red"}
    detail = {"players": [registered, other], "kills": [
        {"round": 0, "time_in_round_in_ms": 1000, "killer": {"puuid": "p2"}, "victim": {"puuid": "p1"}}
    ]}

    text = _play_recap("Haven", False, 8, 13, [], [registered], "30 min", detail, registered_only=True)
    headline = _play_headline([registered], 8, 13, registered_only=True)

    assert "Friend" in text
    assert "Stranger" not in text and "STRANGER" not in headline
    assert "topping the team" not in text


@pytest.mark.parametrize("tone", ["kind", "constructive", "harsh"])
def test_fallback_tone_avoids_default_profanity(tone):
    friend = {"puuid": "p1", "name": "Friend", "stats": {"kills": 3, "deaths": 20, "score": 400}}
    text = _play_recap("Haven", False, 8, 13, [], [friend], "30 min", tone=tone)
    headline = _play_headline([friend], 8, 13, tone=tone)
    assert "Friend" in text and "3/20/0" in text
    assert not any(word in (text + headline).lower() for word in ("fuck", "shit", "bastard"))


@pytest.mark.asyncio
async def test_matchfeed_tone_is_saved_per_server(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("HENRIK_API_KEY", "test-key")
    import bot
    feeds = {"1": {"channel_id": 5, "seen": ["match"]}, "2": {"channel_id": 6}}
    monkeypatch.setattr(bot, "load_matchfeeds", lambda: feeds)
    save = Mock()
    monkeypatch.setattr(bot, "save_matchfeeds", lambda value: save(value))
    interaction = SimpleNamespace(guild=object(), guild_id=1, permissions=SimpleNamespace(administrator=True),
                                  response=SimpleNamespace(send_message=AsyncMock()))
    from commands.matches import MatchesCog
    cog = MatchesCog(bot.make_command_context())
    await cog.matchfeed_tone_cmd.callback(cog, interaction, SimpleNamespace(value="kind"))
    assert feeds["1"]["tone"] == "kind" and "tone" not in feeds["2"]
    assert feeds["1"]["seen"] == ["match"]
    assert save.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("feeds,expected", [({"1": {"tone": "kind"}}, "kind"),
                                          ({"1": {"tone": "constructive"}}, "constructive"),
                                          ({"1": {"tone": "harsh"}}, "harsh"),
                                          ({}, DEFAULT_TONE)])
async def test_play_card_preview_uses_server_tone(monkeypatch, feeds, expected):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("HENRIK_API_KEY", "test-key")
    import bot
    from commands.administration import AdministrationCog

    monkeypatch.setattr(bot, "load_matchfeeds", lambda: feeds)
    render = AsyncMock(return_value=object())
    monkeypatch.setattr(bot, "play_match_image", render)
    interaction = SimpleNamespace(guild=object(), guild_id=1, permissions=SimpleNamespace(administrator=True),
                                  response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    cog = AdministrationCog(bot.make_command_context())
    await cog.test_play_card.callback(cog, interaction)
    assert render.await_args.kwargs["tone"] == expected
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_matchfeed_card_sends_registered_players_to_summary_only(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("HENRIK_API_KEY", "test-key")
    import bot

    friend = {"puuid": "p1", "name": "Friend", "team_id": "Red", "agent": {"id": "agent-id"}}
    stranger = {"puuid": "p2", "name": "Stranger", "team_id": "Red", "agent": {"id": "agent-id"}}
    team = [friend, stranger]
    detail = {"metadata": {"map": {}}, "players": team}
    ai = AsyncMock(return_value=None)
    captured = []

    def render(*args):
        captured.append(args)
        return BytesIO(b"png")

    monkeypatch.setattr(bot.client, "http_session", object(), raising=False)
    monkeypatch.setattr(bot, "icon_img", AsyncMock(return_value=None))
    monkeypatch.setattr(bot, "generate_recap", ai)
    monkeypatch.setattr(bot, "draw_play_result", render)
    card = await bot.play_match_image(detail, [friend], team, friend, summary_players=[friend])
    card.close()

    assert ai.await_args.args[4] == [friend]
    assert ai.await_args.kwargs["registered_only"] is True
    assert captured[0][2] == team
    assert captured[0][6] == [friend]


@pytest.mark.asyncio
async def test_recent_displays_full_scoreboard(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("HENRIK_API_KEY", "test-key")
    import bot

    friend = {"puuid": "p1", "name": "Friend", "tag": "123", "team_id": "Red"}
    teammate = {"puuid": "p2", "name": "Teammate", "tag": "123", "team_id": "Red"}
    stranger = {"puuid": "p3", "name": "Stranger", "tag": "123", "team_id": "Red"}
    outsider = {"puuid": "p4", "name": "Outsider", "tag": "123", "team_id": "Red"}
    team = [friend, teammate, stranger, outsider]
    accounts = {str(i): {"name": name, "tag": "123"} for i, name in
                [(1, "Friend"), (2, "Teammate"), (4, "Outsider")]}
    guild = SimpleNamespace(get_member=lambda user_id: object() if user_id == 2 else None,
                            fetch_member=AsyncMock(return_value=None))
    interaction = SimpleNamespace(user=SimpleNamespace(id=1), guild=guild,
                                  response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    monkeypatch.setattr(bot, "load_accounts", lambda: accounts)
    monkeypatch.setattr(bot, "cached_api", AsyncMock(return_value=[{"meta": {"id": "m1"}, "stats": {"puuid": "p1"}}]))
    monkeypatch.setattr(bot, "cached", AsyncMock(return_value={"players": team}))
    view = SimpleNamespace(card=AsyncMock(return_value=object()))
    render = AsyncMock(return_value=view)
    monkeypatch.setattr(bot, "recent_scoreboard_view", render)

    from commands.matches import MatchesCog
    cog = MatchesCog(bot.make_command_context())
    await cog.recent_cmd.callback(cog, interaction)

    assert render.await_args.args == ({"players": team}, friend)
    view.card.assert_awaited_once_with("full")
    interaction.followup.send.assert_awaited_once()
