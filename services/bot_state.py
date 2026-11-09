"""Access the bot's JSON-backed state files."""

from .json_store import read_json, write_json


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
