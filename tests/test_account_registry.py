import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from commands.player_handlers import register_account
from services.account_registry import deduplicate_accounts
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
