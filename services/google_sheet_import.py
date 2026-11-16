"""Read a shared Google Sheets tab and parse its Premier plans."""

import asyncio
import csv
import io
import re
from urllib.parse import parse_qs, urlsplit

import aiohttp
from yarl import URL


PLAYBOOK_TEMPLATE = """Playbook\tAbyss\tAttack\tA Split
Description\tSplit A through main and mid.
Step\tSmoke heaven before entering from main.
Step\tWait for the mid players before planting.
Utility\tSave one smoke for the retake.
Assignment\tKevin\tSmoke heaven and call the execute.
Link\thttps://example.com/reference"""

SHEET_PATH = re.compile(r"/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]{10,200})(?:/.*)?")
MAX_DOC_BYTES = 128_000


class DocImportError(ValueError):
    pass


async def read_google_sheet(session, link):
    try:
        parsed = urlsplit(link.strip())
        match = SHEET_PATH.fullmatch(parsed.path)
        if parsed.scheme != "https" or parsed.netloc.lower() != "docs.google.com" or not match:
            raise ValueError
    except ValueError:
        raise DocImportError("Paste a Google Sheets sharing link from docs.google.com.") from None

    query = parse_qs(parsed.query)
    url = URL(f"https://docs.google.com/spreadsheets/d/{match[1]}/export").with_query(format="csv")
    gid = parse_qs(parsed.fragment).get("gid", query.get("gid", [""]))[0]
    if re.fullmatch(r"\d{1,20}", gid):
        url = url.update_query(gid=gid)
    resource_key = query.get("resourcekey", [""])[0]
    if re.fullmatch(r"[A-Za-z0-9_-]{1,200}", resource_key):
        url = url.update_query(resourcekey=resource_key)

    try:
        for _ in range(4):
            async with session.get(url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=12)) as response:
                if response.status in (301, 302, 303, 307, 308):
                    url = url.join(URL(response.headers.get("Location", "")))
                    host = url.host or ""
                    if (url.scheme != "https" or url.port != 443 or url.user is not None
                            or (host != "docs.google.com" and not host.endswith(".googleusercontent.com"))):
                        break
                    continue
                if response.status != 200 or response.content_type not in ("text/csv", "application/octet-stream"):
                    break
                data = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > MAX_DOC_BYTES:
                        raise DocImportError("The sheet tab is too large. Split it into smaller imports.")
                return data.decode("utf-8-sig")
    except DocImportError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise DocImportError("The bot couldn't read the Google Sheet. Try again in a moment.") from exc
    raise DocImportError("The bot couldn't open the sheet. Use a link that allows anyone with the link to view it and download it.")


def parse_lineup_sheet(text, map_name):
    rows = list(csv.reader(io.StringIO(text, newline="")))
    headers = [(index, column) for index, row in enumerate(rows) for column, cell in enumerate(row)
               if column >= 2 and cell.strip().casefold() == map_name.casefold()]
    if not headers:
        return None
    if len(headers) > 1:
        raise DocImportError(f"Expected one column headed '{map_name}' in column C or later.")
    header, column = headers[0]
    picks = []
    for number, row in enumerate(rows[header + 1:], start=header + 2):
        agent = row[column].strip() if len(row) > column else ""
        if not agent:
            continue
        player = row[1].strip()
        if not player:
            raise DocImportError(f"Row {number}: enter the player in column B.")
        picks.append((player, agent))
    if not 1 <= len(picks) <= 5:
        raise DocImportError(f"{map_name} needs between one and five player picks.")
    return picks


def parse_playbook_sheet(text):
    strategies = []
    strategy = None
    for number, row in enumerate(csv.reader(io.StringIO(text, newline="")), start=1):
        cells = [cell.strip() for cell in row]
        while cells and not cells[-1]:
            cells.pop()
        if not cells:
            continue
        kind, *values = cells
        kind = kind.casefold()
        expected = {"playbook": 3, "description": 1,
                    "step": 1, "utility": 1, "assignment": 2, "link": 1}.get(kind)
        if expected is None or len(values) != expected or not all(values):
            raise DocImportError(f"Row {number}: check the row type and columns against the /importplaybook template.")
        if kind == "playbook":
            map_name, side, name = values
            side = side.casefold().replace("defense", "defence")
            strategy = {"map": map_name, "side": side, "name": name,
                        "steps": [], "links": [], "assignments": []}
            strategies.append(strategy)
            continue
        if strategy is None:
            raise DocImportError(f"Row {number}: put strategy details below a Playbook row.")
        if kind in ("description", "utility"):
            key = "objective" if kind == "description" else "utility"
            strategy[key] = "\n".join(filter(None, (strategy.get(key), values[0])))
        elif kind in ("step", "link"):
            strategy[kind + "s"].append(values[0])
        elif kind == "assignment":
            strategy["assignments"].append({"player": values[0], "responsibilities": values[1]})
    if not strategies:
        raise DocImportError("The sheet has no playbook sections.")
    if len(strategies) > 40:
        raise DocImportError("Import at most 40 strategies in one sheet tab.")
    return strategies
