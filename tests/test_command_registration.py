import discord
from discord.ext import commands
import pytest
import ast
import importlib
import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

from commands import install_command_cogs


@pytest.mark.asyncio
async def test_command_cogs_preserve_all_slash_command_metadata(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("HENRIK_API_KEY", "test-key")
    import bot

    temporary = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    def metadata(tree):
        return {command.name: (command.description,
                [(p.name, p.required, p.type, p.autocomplete) for p in command.parameters])
                for command in tree.get_commands()}

    await install_command_cogs(temporary, bot.make_command_context())
    commands_by_name = metadata(temporary.tree)
    assert len(commands_by_name) == 28
    assert {"recent", "matchfeed", "matchfeed_tone", "player", "playbook"}.issubset(commands_by_name)
    agent_params = commands_by_name["agent"][1]
    assert [(p[0], p[1], p[3]) for p in agent_params] == [("agent_name", True, True), ("map_name", False, True)]
    assert commands_by_name["recent"][1][0][0] == "player"
    await temporary.close()


def test_application_feature_dependency_bindings():
    modules = {name: f"commands.{name}" for name in
               ("premier_handlers", "player_handlers", "agent_handlers", "playbook_handlers", "admin_handlers")}
    modules.update({name: f"services.{name}" for name in
                    ("asset_helpers", "premier_helpers", "discord_helpers", "account_helpers", "agent_helpers", "playbook_helpers")})
    source = Path(__file__).resolve().parents[1] / "bot.py"
    for call in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name) and call.func.value.id in modules):
            continue
        function = getattr(importlib.import_module(modules[call.func.value.id]), call.func.attr)
        inspect.signature(function).bind(*([None] * len(call.args)),
                                         **{kw.arg: None for kw in call.keywords if kw.arg})


def test_cogs_have_their_runtime_dependencies(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("HENRIK_API_KEY", "test-key")
    import bot

    context = bot.make_command_context()
    from commands.context import CommandContext
    assert isinstance(context, CommandContext)
    with pytest.raises(FrozenInstanceError):
        context.AFFINITY = "na"
    root = Path(__file__).resolve().parents[1] / "commands"
    for filename in ("administration.py", "agents.py", "matches.py", "players.py", "playbooks.py", "premier.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name) and node.value.value.id == "self"
                    and node.value.attr == "runtime"):
                assert hasattr(context, node.attr), f"{filename} requires runtime.{node.attr}"
