"""Identity and duplicate handling for registered Riot accounts."""

from datetime import datetime, timezone


def account_key(account):
    name = str(account.get("name") or "").strip().casefold()
    tag = str(account.get("tag") or "").strip().casefold()
    return (name, tag) if name and tag else None


def account_puuid(account):
    return str(account.get("puuid") or "").strip().casefold() or None


def matching_account(left, right):
    left_key, right_key = account_key(left), account_key(right)
    left_id, right_id = account_puuid(left), account_puuid(right)
    return bool((left_key and left_key == right_key) or (left_id and left_id == right_id))


def _registered_at(account):
    try:
        value = account.get("registered_at")
        if not isinstance(value, str):
            return None
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except ValueError:
        return None


def deduplicate_accounts(accounts):
    """Keep the oldest entry, using JSON order when legacy timestamps are missing."""
    entries = list(accounts.items())
    parents = list(range(len(entries)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, (_, account) in enumerate(entries):
        if not isinstance(account, dict):
            continue
        for earlier in range(index):
            other = entries[earlier][1]
            if isinstance(other, dict) and matching_account(account, other):
                parents[root(index)] = root(earlier)
    groups = {}
    for index in range(len(entries)):
        groups.setdefault(root(index), []).append(index)
    removed = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        dates = [_registered_at(entries[index][1]) for index in group]
        winner = min(zip(group, dates), key=lambda item: item[1])[0] if all(dates) else group[0]
        removed.update(index for index in group if index != winner)
    return ({key: value for index, (key, value) in enumerate(entries) if index not in removed},
            [entries[index][0] for index in sorted(removed)])
