"""Internship notification service. Polls public feeds, posts Discord embeds, deduplicates via SQLite.

Supports Discord webhooks OR a real Discord bot token and channel ID (REST delivery).
The collector does not filter by year, school year, citizenship, or degree.
Set location_scope=US to include only jobs explicitly located in the United States.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from dotenv import load_dotenv

LOG = logging.getLogger("internship-alerts")
ROOT = Path(__file__).resolve().parent
SIMPLIFY_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/"
    "Summer2027-Internships/dev/.github/scripts/listings.json"
)
USER_AGENT = "InternshipAlertBot/1.0 (personal-notification-service)"

# Expressions requiring internship/co-op titles prevent accidentally alerting on full-time jobs.
INTERNSHIP = re.compile(r"\b(?:intern(?:ship)?s?|co[ -]?ops?|working student|student engineer|student assistant|industrial placement)\b", re.I)

# Category, display color and keyword patterns. Patterns deliberately include non-RTL
# electrical hardware (as requested) but exclude plain generic software roles.
CATEGORIES: list[tuple[str, int, list[tuple[str, str]]]] = [
    ("Embedded / Firmware", 0x18B77A, [
        ("embedded", r"\bembedded\b"), ("firmware", r"\bfirmware\b"),
        ("microcontroller", r"\bmicrocontrollers?\b|\bMCUs?\b"),
        ("RTOS", r"\bRTOS\b|\bFreeRTOS\b|\bZephyr\b"),
        ("device drivers", r"\bdevice drivers?\b"),
        ("low-level software", r"\blow.level software\b"),
        ("board support", r"\bboard support packages?\b|\bBSP\b"),
    ]),
    ("RTL / ASIC / FPGA", 0x18B77A, [
        ("RTL", r"\bRTL\b"), ("FPGA", r"\bFPGAs?\b"),
        ("ASIC", r"\bASICs?\b"), ("digital design", r"\bdigital (?:logic |circuit )?design\b"),
        ("SoC", r"\bSoCs?\b|\bsystem.on.chip\b"),
        ("Verilog", r"\b(?:System)?Verilog\b"), ("VHDL", r"\bVHDL\b"),
        ("design verification", r"\b(?:design |functional )?verification\b|\bUVM\b"),
        ("logic synthesis", r"\blogic synthesis\b"),
    ]),
    ("Hardware / Circuits", 0x18B77A, [
        ("hardware", r"\bhardware(?: engineering| design| development| test)?\b"),
        ("circuit design", r"\bcircuit(?:s)? (?:design|engineering)\b"),
        ("PCB", r"\bPCB\b|\bprinted circuit board\b"),
        ("electronics", r"\belectronics?\b"),
        ("electrical engineering", r"\belectrical engineering\b"),
        ("mixed-signal", r"\bmixed.signal\b"),
        ("analog", r"\banalog\b"),
        ("power electronics", r"\bpower electronics\b"),
        ("electrical design", r"\belectrical design\b"),
    ]),
    ("Semiconductor / Silicon", 0x8B5CF6, [
        ("semiconductor", r"\bsemiconductors?\b"),
        ("silicon", r"\bsilicon\b"),
        ("VLSI", r"\bVLSI\b"),
        ("physical design", r"\bphysical design\b"),
        ("DFT", r"\bDFT\b|\bdesign.for.test\b"),
        ("chip design", r"\bchip (?:design|development)\b"),
        ("device engineering", r"\bdevice engineering\b"),
        ("reliability", r"\breliability engineering\b"),
    ]),
    ("Signal Integrity / RF", 0x8B5CF6, [
        ("signal integrity", r"\bsignal integrity\b"),
        ("power integrity", r"\bpower integrity\b"),
        ("RF", r"\bRF\b|\bradio.frequency\b"),
        ("microwave", r"\bmicrowave\b"),
        ("high-speed", r"\bhigh.speed (?:interconnect|design|interface)\b"),
    ]),
    ("Photonics", 0x8B5CF6, [
        ("photonics", r"\bphotonic[s]?\b"),
        ("optical engineering", r"\boptical (?:engineering|hardware|devices?)\b"),
        ("optoelectronics", r"\boptoelectronics?\b"),
    ]),
]
COMPILED = [(name, color, [(term, re.compile(pattern, re.I)) for term, pattern in pairs])
            for name, color, pairs in CATEGORIES]
SEASON = re.compile(r"\b(?:spring|summer|fall|autumn|winter)\s*20\d{2}\b", re.I)


# A conservative U.S.-only filter. ATS feeds often supply unstructured locations.
# Missing/ambiguous locations (e.g. only "Remote") are excluded in US mode.
# Multi-location postings qualify when at least one explicitly U.S. location exists.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA",
    "WA", "WV", "WI", "WY", "DC",
}
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}
US_COUNTRY = re.compile(r"(?<![a-z])(?:united states(?: of america)?|u\.?s\.?a\.?|u\.?s\.?)(?![a-z])", re.I)
US_CITY_SHORT = re.compile(r"(?<![a-z])(?:NYC|SF|DC|Washington, D\.?C\.?)(?![a-z])", re.I)
US_STATE_CODES = re.compile(r"(?:,|/|\||\(|\s-\s)\s*([A-Z]{2})(?=\s*(?:$|[,/|;)\-]))")


def is_us_location(location: str) -> bool:
    """Return True only when there is explicit evidence of a U.S. work location.

    'Remote' by itself is not enough; 'Remote - US' or 'US Remote' is.
    """
    if not location or not location.strip():
        return False
    if US_COUNTRY.search(location) or US_CITY_SHORT.search(location):
        return True
    if any(state in US_STATES for state in US_STATE_CODES.findall(location)):
        return True
    normalized = location.lower()
    if any(re.search(r"(?<![a-z])" + re.escape(state) + r"(?![a-z])", normalized)
           for state in US_STATE_NAMES):
        return True
    return False


@dataclass(frozen=True)
class Job:
    source: str
    external_id: str
    company: str
    title: str
    location: str
    url: str
    posted: str = ""  # ISO date or YYYY-MM-DD; omitted when publication date unknown.
    term: str = ""
    description: str = ""


def fetch_json(session: requests.Session, url: str, **kwargs: Any) -> Any:
    response = session.get(url, timeout=(8, 45), **kwargs)
    response.raise_for_status()
    return response.json()


def simplify_jobs(session: requests.Session) -> Iterator[Job]:
    data = fetch_json(session, SIMPLIFY_URL)
    if isinstance(data, dict):
        data = data.get("listings", data.get("jobs", []))
    if not isinstance(data, list):
        raise ValueError("Unexpected Simplify listings data format")
    for item in data:
        if not isinstance(item, dict) or not item.get("active", True) or not item.get("is_visible", True):
            continue
        title, url = str(item.get("title") or ""), str(item.get("url") or "")
        if not title or not url:
            continue
        date = item.get("date_posted")
        posted = ""
        if isinstance(date, (int, float)) and date > 0:
            posted = datetime.fromtimestamp(date, tz=timezone.utc).date().isoformat()
        locations = item.get("locations") or []
        terms = item.get("terms") or []
        yield Job(
            source="Simplify", external_id=str(item.get("id") or url),
            company=str(item.get("company_name") or "Unknown"), title=title,
            location=", ".join(str(x) for x in locations) if isinstance(locations, list) else str(locations),
            url=url, posted=posted,
            term=", ".join(str(x) for x in terms) if isinstance(terms, list) else str(terms),
        )


def greenhouse_jobs(session: requests.Session, company: str, slug: str) -> Iterator[Job]:
    data = fetch_json(session, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    for item in data.get("jobs", []):
        title = item.get("title") or ""
        desc = item.get("content") or ""
        url = item.get("absolute_url") or ""
        if not title or not url:
            continue
        # Greenhouse updated_at is NOT necessarily when the job was posted.
        yield Job("Greenhouse", str(item.get("id") or url), company, title,
                  (item.get("location") or {}).get("name") or "", url,
                  term=extract_term(title), description=desc)


def lever_jobs(session: requests.Session, company: str, slug: str) -> Iterator[Job]:
    # Lever supports pagination. Some boards have >100 postings.
    for skip in range(0, 5000, 100):
        batch = fetch_json(session, f"https://api.lever.co/v0/postings/{slug}",
                           params={"mode": "json", "skip": skip, "limit": 100})
        if not isinstance(batch, list):
            raise ValueError("Unexpected Lever response")
        for item in batch:
            categories = item.get("categories") or {}
            posted = ""
            created = item.get("createdAt")
            if isinstance(created, (int, float)) and created > 0:
                posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()
            desc = item.get("descriptionPlain") or item.get("description") or ""
            desc += " " + " ".join(str(x) for x in (item.get("lists") or []))
            title = item.get("text") or ""
            url = item.get("hostedUrl") or item.get("applyUrl") or ""
            if title and url:
                yield Job("Lever", str(item.get("id") or url), company, title,
                          categories.get("location") or "", url, posted,
                          extract_term(title + " " + str(categories.get("commitment") or "")), desc)
        if len(batch) < 100:
            return
    LOG.warning("Lever board %s exceeded pagination safety cap", slug)


def ashby_jobs(session: requests.Session, company: str, slug: str) -> Iterator[Job]:
    data = fetch_json(session, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for item in data.get("jobs", []):
        if not item.get("isListed", True):
            continue
        title, url = item.get("title") or "", item.get("jobUrl") or item.get("applyUrl") or ""
        if not title or not url:
            continue
        locations = [item.get("location") or ""] + [
            other.get("location") or "" for other in item.get("secondaryLocations", [])
        ]
        yield Job("Ashby", url, company, title, ", ".join(x for x in locations if x), url,
                  posted=item.get("publishedAt") or "",
                  term=extract_term(title), description=item.get("descriptionPlain") or "")


def extract_term(text: str) -> str:
    return ", ".join(dict.fromkeys(m.group(0) for m in SEASON.finditer(text)))


def classify(job: Job) -> tuple[str, int, int, list[str]] | None:
    if not INTERNSHIP.search(job.title):
        return None
    # Score prioritizes title specificity over generic description matches.
    best: tuple[int, int, str, int, list[str]] | None = None
    for category, color, terms in COMPILED:
        title_hits = [term for term, rex in terms if rex.search(job.title)]
        description_hits = [term for term, rex in terms if rex.search(job.description[:12000])]
        matches = list(dict.fromkeys(title_hits + description_hits))
        if not matches:
            continue
        # Avoid generic internships if the only evidence is one passing description keyword.
        if not title_hits and len(description_hits) < 2:
            continue
        score = min(10, 2 + 2 * len(title_hits) + min(3, len(description_hits)))
        rank = (score, len(title_hits), category, color, matches)
        if best is None or rank[:2] > best[:2]:
            best = rank
    if best is None:
        return None
    # Explain the match using terms across all categories, ordered as they appear
    # in the title (e.g. "silicon photonics reliability" from the example).
    title_matches: list[tuple[int, str]] = []
    desc_matches: list[str] = []
    for _, _, terms in COMPILED:
        for term, pattern in terms:
            match = pattern.search(job.title)
            if match:
                title_matches.append((match.start(), term))
            elif pattern.search(job.description[:12000]):
                desc_matches.append(term)
    ordered = [term for _, term in sorted(title_matches)] + desc_matches
    return best[2], best[3], best[0], list(dict.fromkeys(ordered))[:5]


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    # Strip referral/tracking parameters, but preserve meaningful ones (jobId, gh_jid, etc.).
    query = sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in
                   {"ref", "source", "gh_src", "ghsource", "gh_jid_source", "trackingid"})
    return urlunparse((parsed.scheme.lower() or "https", host,
                       parsed.path.rstrip("/"), "", urlencode(query), ""))


def job_key(job: Job) -> str:
    # Cross-source dedup works when Simplify links to the same ATS posting.
    return hashlib.sha256(canonical_url(job.url).encode("utf-8")).hexdigest()


def display_date(text: str) -> str:
    if not text:
        return "Not provided"
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return f"{d:%b} {d.day}, {d:%Y}"
    except ValueError:
        return "Not provided"


def safe(text: str, limit: int = 1024) -> str:
    # Also suppress Discord formatting in plain fields to avoid unintended mentions.
    return str(text).replace("@", "＠")[:limit] or "Not provided"


def embed(job: Job, classification: tuple[str, int, int, list[str]]) -> dict[str, Any]:
    category, color, score, matches = classification
    return {
        "title": safe(job.title, 256), "url": job.url, "color": color,
        "fields": [
            {"name": "Company", "value": safe(job.company), "inline": True},
            {"name": "Location", "value": safe(job.location or "Not provided"), "inline": True},
            {"name": "Posted", "value": display_date(job.posted), "inline": True},
            {"name": "Term", "value": safe(job.term or "Not specified"), "inline": False},
            {"name": "Matched on", "value": " ".join(f"`{safe(x, 50)}`" for x in matches), "inline": False},
        ],
        "footer": {"text": f"{category} | Score {score}/10 | via {job.source}"},
    }


class State:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS seen (job_key TEXT PRIMARY KEY, first_seen TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS initialized (source TEXT PRIMARY KEY)")
        self.connection.commit()

    def is_seen(self, key: str) -> bool:
        return self.connection.execute("SELECT 1 FROM seen WHERE job_key=?", (key,)).fetchone() is not None

    def mark(self, key: str) -> None:
        self.connection.execute("INSERT OR IGNORE INTO seen VALUES (?, datetime('now'))", (key,))
        self.connection.commit()

    def is_initialized(self, source: str) -> bool:
        return self.connection.execute("SELECT 1 FROM initialized WHERE source=?", (source,)).fetchone() is not None

    def initialize(self, source: str) -> None:
        self.connection.execute("INSERT OR IGNORE INTO initialized VALUES (?)", (source,))
        self.connection.commit()


def discord_send(payload: dict[str, Any], session: requests.Session) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel = os.getenv("DISCORD_CHANNEL_ID", "").strip()
    if webhook:
        url = webhook
        headers = {}
    elif token and channel:
        url = f"https://discord.com/api/v10/channels/{channel}/messages"
        headers = {"Authorization": f"Bot {token}"}
    else:
        raise RuntimeError("Configure DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID")
    headers["User-Agent"] = USER_AGENT
    for attempt in range(4):
        response = session.post(url, json=payload, headers=headers, timeout=(8, 30))
        if 200 <= response.status_code < 300:
            return
        if response.status_code == 429 and attempt < 3:
            retry = response.json().get("retry_after", 2)
            time.sleep(max(1, min(30, float(retry))))
            continue
        response.raise_for_status()
    raise RuntimeError("Discord rate limit retries exhausted")


def sources(config: dict[str, Any], session: requests.Session) -> Iterator[tuple[str, Any]]:
    if config.get("simplify_2027", True):
        yield "Simplify 2027", lambda: simplify_jobs(session)
    for company, slug in (config.get("greenhouse") or {}).items():
        yield f"Greenhouse:{slug}", lambda c=company, s=slug: greenhouse_jobs(session, c, s)
    for company, slug in (config.get("lever") or {}).items():
        yield f"Lever:{slug}", lambda c=company, s=slug: lever_jobs(session, c, s)
    for company, slug in (config.get("ashby") or {}).items():
        yield f"Ashby:{slug}", lambda c=company, s=slug: ashby_jobs(session, c, s)


def run_cycle(config: dict[str, Any], state: State, session: requests.Session, *, dry_run: bool = False) -> int:
    alerts = 0
    cap = max(1, int(config.get("max_alerts_per_cycle", 50)))
    us_only = str(config.get("location_scope", "US")).upper() == "US"
    bootstrap = os.getenv("BOOTSTRAP_MODE", "skip_existing")
    for source_name, loader in sources(config, session):
        if alerts >= cap:
            break
        try:
            # Fetch completely before marking source initialized, so incomplete fetches don't silently lose data.
            postings = list(loader())
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOG.warning("Unable to poll %s: %s", source_name, exc)
            continue
        first_success = not state.is_initialized(source_name)
        matched = 0
        for job in postings:
            if us_only and not is_us_location(job.location):
                continue
            label = classify(job)
            if label is None:
                continue
            matched += 1
            key = job_key(job)
            if state.is_seen(key):
                continue
            if first_success and bootstrap == "skip_existing" and not dry_run:
                if not dry_run:
                    state.mark(key)
                continue
            if dry_run:
                LOG.info("[DRY RUN] %s | %s | %s", job.company, job.title, job.url)
                alerts += 1
            else:
                try:
                    discord_send({"embeds": [embed(job, label)], "allowed_mentions": {"parse": []}}, session)
                except (requests.RequestException, RuntimeError, ValueError) as exc:
                    LOG.error("Discord delivery failed for %s: %s", job.url, exc)
                    # Do not mark as seen: retry on the next cycle.
                    continue
                state.mark(key)
                alerts += 1
            if alerts >= cap:
                break
        if not dry_run:
            state.initialize(source_name)
        LOG.info("%s: %d listings, %d matched", source_name, len(postings), matched)
    return alerts


def sample_job() -> Job:
    return Job("Simplify", "demo", "GlobalFoundries",
               "Silicon Photonics Reliability Engineering Intern",
               "Malta, NY", "https://www.example.com/internship",
               "2026-09-28", "Summer 2027")


def main() -> None:
    parser = argparse.ArgumentParser(description="Embedded / hardware / RTL internship Discord alerts")
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print new matches without sending, and leave state untouched")
    parser.add_argument("--preview", action="store_true", help="Print the example Discord embed JSON; no network")
    parser.add_argument("--send-test", action="store_true", help="Send an example Discord embed only")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    demo = sample_job()
    if args.preview:
        print(json.dumps({"embeds": [embed(demo, classify(demo))]}, indent=2))
        return
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    if args.send_test:
        discord_send({"embeds": [embed(demo, classify(demo))], "allowed_mentions": {"parse": []}}, session)
        LOG.info("Test notification sent")
        return
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    db_path = os.getenv("DATABASE_PATH", "seen_jobs.sqlite3")
    if db_path != ":memory:" and not Path(db_path).is_absolute():
        db_path = str(ROOT / db_path)
    state = State(":memory:" if args.dry_run else db_path)
    while True:
        try:
            count = run_cycle(config, state, session, dry_run=args.dry_run)
            LOG.info("Cycle complete: %d new alerts", count)
        except Exception:
            LOG.exception("Unexpected cycle error")
        if args.once or args.dry_run:
            return
        time.sleep(max(60, int(os.getenv("POLL_SECONDS", "900"))))


if __name__ == "__main__":
    main()
