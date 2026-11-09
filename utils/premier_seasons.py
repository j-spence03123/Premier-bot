"""Normalize Premier season API responses."""


def extract_premier_seasons(data):
    """Normalize the Premier seasons endpoint into newest-first {id, name} records."""
    source = data
    if isinstance(source, dict):
        source = source.get("seasons") or source.get("data") or source.get("premier_seasons") or source
    if isinstance(source, dict):
        if source.get("id") or source.get("season_id"):
            source = [source]
        else:
            source = [dict(value, id=value.get("id") or value.get("season_id") or key)
                      for key, value in source.items() if isinstance(value, dict)]
    if not isinstance(source, list):
        return []

    records, seen = [], set()
    for item in source:
        if not isinstance(item, dict):
            continue
        nested = item.get("season") if isinstance(item.get("season"), dict) else {}
        season_id = item.get("season_id") or item.get("id") or nested.get("id")
        if not season_id or str(season_id) in seen:
            continue
        seen.add(str(season_id))
        name = item.get("name") or item.get("short") or item.get("label") or nested.get("short") or str(season_id)
        records.append({"id": str(season_id), "name": str(name)})
    # HenrikDev returns Premier seasons oldest first; scout from the current season backwards.
    return list(reversed(records))
