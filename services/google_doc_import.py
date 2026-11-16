"""Read a shared Google Doc and parse its lineup and playbook sections."""

import asyncio
import re
from urllib.parse import parse_qs, urlsplit

import aiohttp
from yarl import URL


TEMPLATE = """[Lineup: Week 6]
Kevin#1234 = Omen
Spam#5678 = Cypher

[Playbook: Abyss | Attack | A Split]
Description: Split A through main and mid.
Step: Smoke heaven before entering from main.
Step: Wait for the mid players to reach site before planting.
Utility: Save one smoke for the retake.
Assignment: Kevin | Smoke heaven and call the execute.
Link: https://example.com/reference"""

DOC_PATH = re.compile(r"/document/(?:u/\d+/)?d/([A-Za-z0-9_-]{10,200})(?:/.*)?")
MAX_DOC_BYTES = 128_000


class DocImportError(ValueError):
    pass


async def read_google_doc(session, link):
    try:
        parsed = urlsplit(link.strip())
        match = DOC_PATH.fullmatch(parsed.path)
        if parsed.scheme != "https" or parsed.netloc.lower() != "docs.google.com" or not match:
            raise ValueError
    except ValueError:
        raise DocImportError("Paste a Google Docs sharing link from docs.google.com.") from None

    url = URL(f"https://docs.google.com/document/d/{match[1]}/export").with_query(format="txt")
    resource_key = parse_qs(parsed.query).get("resourcekey", [""])[0]
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
                if response.status != 200 or response.content_type != "text/plain":
                    break
                data = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > MAX_DOC_BYTES:
                        raise DocImportError("The Google Doc is too large. Split it into smaller imports.")
                return data.decode("utf-8-sig")
    except DocImportError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise DocImportError("The bot couldn't read the Google Doc. Try again in a moment.") from exc
    raise DocImportError("The bot couldn't open the document. Use a link that allows anyone with the link to view it and download it.")


def parse_import_document(text):
    lineups = []
    strategies = []
    lineup = strategy = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            kind, separator, value = line[1:-1].partition(":")
            kind, value = kind.strip().casefold(), value.strip()
            lineup = strategy = None
            if separator and kind == "lineup" and value:
                lineup = []
                lineups.append((value, lineup))
            elif separator and kind == "playbook":
                parts = [part.strip() for part in value.split("|", 2)]
                if len(parts) != 3 or not all(parts):
                    raise DocImportError(f"Line {number}: use [Playbook: Map | Attack or Defence | Strategy name].")
                map_name, side, name = parts
                side = side.casefold().replace("defense", "defence")
                strategy = {"map": map_name, "side": side, "name": name,
                            "steps": [], "links": [], "assignments": []}
                strategies.append(strategy)
            else:
                raise DocImportError(f"Line {number}: expected a [Lineup: Week …] or [Playbook: …] heading.")
            continue
        if lineup is not None:
            player, separator, agent = line.partition("=")
            if not separator or not player.strip() or not agent.strip():
                raise DocImportError(f"Line {number}: enter one player and agent as Player#Tag = Agent.")
            lineup.append((player.strip(), agent.strip()))
            continue
        field, separator, value = line.partition(":")
        field, value = field.strip().casefold(), value.strip()
        if strategy is None or not separator or not value:
            raise DocImportError(f"Line {number}: expected a section heading or a playbook field with text.")
        if field in ("description", "utility"):
            key = "objective" if field == "description" else "utility"
            strategy[key] = "\n".join(filter(None, (strategy.get(key), value)))
        elif field in ("step", "link"):
            strategy[field + "s"].append(value)
        elif field == "assignment":
            player, divider, task = value.partition("|")
            if not divider or not player.strip() or not task.strip():
                raise DocImportError(f"Line {number}: use Assignment: Player | Responsibilities.")
            strategy["assignments"].append({"player": player.strip(), "responsibilities": task.strip()})
        else:
            raise DocImportError(f"Line {number}: unknown playbook field. Use Description, Step, Utility, Assignment or Link.")
    if not lineups and not strategies:
        raise DocImportError("The document has no lineup or playbook sections.")
    if len(lineups) > 15 or len(strategies) > 40:
        raise DocImportError("Import at most 15 lineups and 40 strategies in one document.")
    return lineups, strategies
