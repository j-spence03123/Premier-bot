"""Access the bot's JSON-backed state files."""

from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from .account_registry import deduplicate_accounts
from .json_store import JsonStoreError, read_json, write_json


class BotState:
    def __init__(self, settings):
        self.settings = settings

    def _read(self, path):
        return read_json(path, {})

    def _write(self, path, value):
        write_json(path, value, indent=1)

    def load_accounts(self):
        return self._read(self.settings.accounts_file)

    def save_accounts(self, value):
        self._write(self.settings.accounts_file, value)

    def remove_duplicate_accounts(self):
        """Back up existing account data and remove duplicate links on startup."""
        accounts = self.load_accounts()
        cleaned, removed = deduplicate_accounts(accounts)
        if not removed:
            return []
        path = Path(self.settings.accounts_file)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.duplicates-{stamp}-{uuid4().hex[:8]}.bak")
        try:
            raw = path.read_bytes()
            with backup.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            raise JsonStoreError(f"Could not back up {path.name}; duplicate cleanup was not performed") from exc
        self.save_accounts(cleaned)
        return removed

    def load_play_sessions(self):
        return self._read(self.settings.play_sessions_file)

    def save_play_sessions(self, value):
        self._write(self.settings.play_sessions_file, value)

    def load_matchfeeds(self):
        return self._read(self.settings.matchfeeds_file)

    def save_matchfeeds(self, value):
        self._write(self.settings.matchfeeds_file, value)

    def load_rank_states(self):
        return self._read(self.settings.rankstates_file)

    def save_rank_states(self, value):
        self._write(self.settings.rankstates_file, value)

    def load_queue_schedules(self):
        return self._read(self.settings.queue_schedule_file)

    def save_queue_schedules(self, value):
        write_json(self.settings.queue_schedule_file, value, indent=2)

    def load_agents(self):
        return self._read(self.settings.agents_file)

    def save_agents(self, value):
        self._write(self.settings.agents_file, value)
