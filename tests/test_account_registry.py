import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from commands.player_handlers import register_account, unregister
from commands.players import PlayersCog
from services.account_registry import deduplicate_accounts, select_linked_account
from services.bot_state import BotState
from utils.riot_id import split_riot_id


def test_duplicate_cleanup_uses_legacy_order_and_timestamp():
    accounts = {
        "1": {"name": "Friend", "tag": "EU"},
        "2": {"name": " FRIEND ", "tag": "eu"},
        "3": {"name": "Later", "tag": "T", "puuid": "same", "registered_at": "2026-11-02T00:00:00Z"},
        "4": {"name": "Earlier", "tag": "T", "puuid": "SAME", "registered_at": "2026-11-01T00:00:00Z"},
    }
    cleaned, removed = deduplicate_accounts(accounts)
    assert list(cleaned) == ["1", "4"]
    assert removed == ["2", "3"]


def test_duplicate_cleanup_backs_up_original_file(tmp_path):
    path = tmp_path / "accounts.json"
    original = {"1": {"name": "One", "tag": "EU"}, "2": {"name": "one", "tag": "eu"}}
    path.write_text(json.dumps(original), encoding="utf8")
    state = BotState(SimpleNamespace(accounts_file=path))
    assert state.remove_duplicate_accounts() == ["2"]
    backups = list(tmp_path.glob("accounts.json.duplicates-*.bak"))
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf8")) == original
    assert list(state.load_accounts()) == ["1"]
    assert state.remove_duplicate_accounts() == []
    assert len(list(tmp_path.glob("*.bak"))) == 1


@pytest.mark.asyncio
async def test_duplicate_registration_is_rejected_case_insensitively():
    accounts = {"1": {"name": "Friend", "tag": "EU", "region": "eu"}}
    interaction = SimpleNamespace(user=SimpleNamespace(id=2), response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    api, save = AsyncMock(), Mock()
    await register_account(interaction, interaction.user, "friend#eu", "na", AFFINITY="eu", REGIONS={"eu", "na"},
                           cached_api=api, load_accounts=lambda: accounts, save_accounts=save, split_riot_id=split_riot_id)
    save.assert_not_called()
    api.assert_not_awaited()
    assert "already registered" in interaction.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_registration_rechecks_puuid_after_api_lookup():
    accounts = {"1": {"name": "OldName", "tag": "EU", "puuid": "uuid"}}
    interaction = SimpleNamespace(user=SimpleNamespace(id=2), response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    api = AsyncMock(return_value={"account": {"name": "NewName", "tag": "EU", "puuid": "uuid"}})
    save = Mock()
    await register_account(interaction, interaction.user, "NewName#EU", "eu", AFFINITY="eu", REGIONS={"eu"},
                           cached_api=api, load_accounts=lambda: accounts, save_accounts=save, split_riot_id=split_riot_id)
    save.assert_not_called()
    assert "already registered" in interaction.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_registration_retains_time_when_same_user_registers_again():
    accounts = {"1": {"name": "Friend", "tag": "EU", "registered_at": "2026-01-01T00:00:00Z"}}
    interaction = SimpleNamespace(user=SimpleNamespace(id=1), response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    api = AsyncMock(return_value={"account": {"puuid": "uuid"}})
    await register_account(interaction, interaction.user, "friend#EU", "eu", AFFINITY="eu", REGIONS={"eu"},
                           cached_api=api, load_accounts=lambda: accounts, save_accounts=Mock(), split_riot_id=split_riot_id)
    assert accounts["1"]["registered_at"] == "2026-01-01T00:00:00Z"
    assert accounts["1"]["puuid"] == "uuid"


@pytest.mark.asyncio
async def test_smurf_registration_requires_main_respects_limit_and_frees_a_slot():
    accounts = {}
    interaction = SimpleNamespace(user=SimpleNamespace(id=1), response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    api = AsyncMock(return_value={})
    save = Mock()

    async def register(riot_id, smurf=True):
        await register_account(interaction, interaction.user, riot_id, "", AFFINITY="eu", REGIONS={"eu", "na"},
                               cached_api=api, load_accounts=lambda: accounts, save_accounts=save,
                               split_riot_id=split_riot_id, smurf=smurf)

    await register("First#NA")
    assert "main" in interaction.followup.send.await_args.args[0]
    api.assert_not_awaited()
    accounts["1"] = {"name": "Main", "tag": "NA", "region": "na"}
    await register("First#NA")
    await register("Second#NA")
    await register("Third#NA")
    assert "up to 2" in interaction.followup.send.await_args.args[0]
    assert [smurf["name"] for smurf in accounts["1"]["smurfs"]] == ["First", "Second"]
    assert accounts["1"]["smurfs"][0]["region"] == "na"
    assert api.await_count == 2

    await register("NewMain#EU", smurf=False)
    assert accounts["1"]["name"] == "NewMain"
    assert select_linked_account(accounts["1"], "Smurf 2")["name"] == "Second"
    await unregister(interaction, "FIRST#na", load_accounts=lambda: accounts, save_accounts=save)
    await register("Third#NA")
    assert select_linked_account(accounts["1"], "Smurf 2")["name"] == "Third"


@pytest.mark.asyncio
async def test_smurf_puuid_is_checked_against_other_users_smurfs():
    accounts = {
        "1": {"name": "Main", "tag": "EU", "smurfs": [{"name": "Old", "tag": "EU", "puuid": "alt-id"}]},
        "2": {"name": "Other", "tag": "EU"},
    }
    interaction = SimpleNamespace(user=SimpleNamespace(id=2), response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    api = AsyncMock(return_value={"account": {"name": "Renamed", "tag": "EU", "puuid": "alt-id"}})
    save = Mock()
    await register_account(interaction, interaction.user, "Renamed#EU", "eu", AFFINITY="eu", REGIONS={"eu"},
                           cached_api=api, load_accounts=lambda: accounts, save_accounts=save,
                           split_riot_id=split_riot_id, smurf=True)
    save.assert_not_called()
    assert "already registered to another user" in interaction.followup.send.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("administrator, other_member", [(False, False), (False, True), (True, True)])
async def test_registersmurf_permissions(administrator, other_member):
    user, member = SimpleNamespace(id=1), SimpleNamespace(id=2)
    interaction = SimpleNamespace(
        user=user, guild=object(), permissions=SimpleNamespace(administrator=administrator),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    register = AsyncMock()
    cog = PlayersCog(SimpleNamespace(register_account=register))
    await cog.registersmurf.callback(cog, interaction, "Alt#EU", member=member if other_member else None)
    if other_member and not administrator:
        register.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()
    else:
        register.assert_awaited_once_with(interaction, member if other_member else user, "Alt#EU", "", smurf=True)
