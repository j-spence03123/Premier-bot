"""Aggregate per-match rank changes without treating missing values as zero."""


def session_rr_totals(session):
    matches = session["matches"]
    players = {}
    for match in matches:
        for entry in match.get("rr_changes", []):
            players.setdefault(entry["player_id"], entry["player"])
    if not players:
        players = {name: name for name in session["players"]}
    totals = []
    for player_id, name in players.items():
        values = []
        for match in matches:
            entry = next((item for item in match.get("rr_changes", []) if item["player_id"] == player_id), {})
            if type(entry.get("change")) is int:
                values.append(entry["change"])
        totals.append({
            "player": name, "rr": sum(values) if len(values) == len(matches) else None,
            "covered_games": len(values), "total_games": len(matches),
        })
    return totals
