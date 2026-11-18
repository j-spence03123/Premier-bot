from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from commands import squad_lore as commands
from services.match_images import play_match_image
from services.squad_lore import BETWEEN_SAME_CALLBACK, prepare_squad_context, remember_squad_callback


START = datetime(2026, 11, 18, tzinfo=timezone.utc)


def advance(feed, members, index, score=(5, 13), map_name="Haven", highlights=()):
    facts = {"map": map_name, "rounds": dict(zip(("won", "lost"), score)), "round_highlights": highlights,
             "teammates": [{"name": name} for name in members.values()]}
    memory, context, key = prepare_squad_context(feed, members, f"match-{index}", START + timedelta(hours=index), facts)
    feed["match_counts"] = {"squad_memory": memory}
    return context, key


def test_lineup_history_uses_discord_members_and_verified_map_results():
    feed = {}
    duo = {"1": "One", "2": "Two"}
    assert not advance(feed, duo, 1)[0]
    assert not advance(feed, duo, 2, map_name="Ascent")[0]
    assert not advance(feed, duo, 3)[0]
    assert not advance(feed, {"1": "One", "3": "Three"}, 4)[0]
    assert "third recorded loss in a row on Haven" in advance(feed, {"1": "Alt", "2": "Two"}, 5)[0]["history"]
    assert "broke a run of 3 recorded losses on Haven" in advance(feed, duo, 6, score=(13, 9))[0]["history"]
    for game in range(7, 11):
        assert not advance(feed, duo, game, score=(13, 11))[0]
    assert advance(feed, duo, 11, score=(13, 11))[0]["history"] == "This was the 10th match recorded for this lineup."


def test_callback_requires_the_selected_player_map_and_event_then_observes_cooldown():
    feed = {"squad_lore": {"sheriff express": {"label": "Sheriff Express", "kind": "inside joke", "trigger": "ace",
                                              "member_id": "1", "map": "Haven"}}}
    members = {"1": "One"}
    ace = [{"round": 1, "multikills": [{"player": "One", "ace": True, "kills": 5}]}]
    assert not advance(feed, members, 1)[0]
    assert not advance(feed, members, 2, map_name="Bind", highlights=ace)[0]
    assert not advance(feed, {"2": "One"}, 3, highlights=ace)[0]
    context, key = advance(feed, members, 4, highlights=ace)
    assert context["callback"]["match_evidence"] == "One aced in round 1."
    assert advance(feed, members, 5, highlights=ace)[1] == key
    remember_squad_callback(feed["match_counts"]["squad_memory"], key)
    for offset in range(1, BETWEEN_SAME_CALLBACK + 1):
        assert not advance(feed, members, 5 + offset, highlights=ace)[0]
    assert advance(feed, members, 6 + BETWEEN_SAME_CALLBACK, highlights=ace)[1] == key


@pytest.mark.asyncio
async def test_admin_can_set_list_and_remove_lore_by_label_without_touching_other_servers():
    feeds = {"1": {"channel_id": 2}, "3": {"channel_id": 4, "squad_lore": {}}}
    interaction = SimpleNamespace(guild=object(), guild_id=1, permissions=SimpleNamespace(administrator=False),
                                  response=SimpleNamespace(send_message=AsyncMock()))
    save = Mock()
    deps = {"load_matchfeeds": lambda: feeds, "save_matchfeeds": save}
    await commands.set_entry(interaction, "Clutch  Allergy", "loss", None, "Haven", False, **deps)
    save.assert_not_called()
    interaction.permissions.administrator = True
    await commands.set_entry(interaction, "Clutch  Allergy", "loss", None, "Haven", False, **deps)
    assert feeds["1"]["squad_lore"]["clutch allergy"]["map"] == "Haven"
    assert feeds["3"]["squad_lore"] == {}
    await commands.list_entries(interaction, load_matchfeeds=deps["load_matchfeeds"])
    assert interaction.response.send_message.await_args.kwargs["embed"].fields[0].name == "Clutch Allergy"
    await commands.remove_entry(interaction, "clutch allergy", **deps)
    assert not feeds["1"]["squad_lore"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text,used", [("Clutch Allergy is back.", True), ("The match slipped away.", False)])
async def test_rendered_card_records_whether_the_writer_used_the_optional_callback(text, used):
    player = {"name": "One", "team_id": "Red", "puuid": "1", "agent": {"id": "omen"}}
    context = {"callback": {"label": "Clutch Allergy", "kind": "inside joke",
                            "match_evidence": "The team recorded a loss."}}
    recap = AsyncMock(return_value={"headline": "Haven recap", "recap": text})
    card = await play_match_image(
        {}, [player], [player], player, summary_players=[player], squad_context=context,
        map_background_path=AsyncMock(), icon_maps=AsyncMock(), icon_img=AsyncMock(),
        session=None, api_key="test", model="test", generate_recap=recap,
        draw_play_result=Mock(return_value=BytesIO(b"image")),
    )
    try:
        assert recap.await_args.kwargs["squad_context"] == context
        assert card.squad_callback_used is used
    finally:
        card.close()
