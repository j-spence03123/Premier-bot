"""Feature helpers with explicitly supplied application dependencies."""

def resolve_player(caller, member, name, tag, region, *, load_accounts, split_riot_id):
    """Return (name, tag, region) from typed input, a selected Discord member, or the caller's registered account."""
    if name and (not tag) and ('#' in name):
        parts = split_riot_id(name)
        if parts:
            name, tag = parts
    if name and tag:
        return (name, tag, region)
    if name or tag:
        return None
    acc = load_accounts().get(str((member or caller).id))
    if not acc:
        return None
    return (acc['name'], acc['tag'], region or acc.get('region', ''))

def save_matchfeed_progress(snapshot, guild_key, *, load_matchfeeds, save_matchfeeds):
    """Merge a poller's `seen` update without replacing newer admin settings."""
    updated = snapshot.get(guild_key)
    latest = load_matchfeeds()
    current = latest.get(guild_key)
    if not updated or not current:
        return False
    if (current.get('channel_id'), current.get('started_at')) != (updated.get('channel_id'), updated.get('started_at')):
        return False
    current['seen'] = list(updated.get('seen', []))
    save_matchfeeds(latest)
    return True
