"""Additional no-auth public internship sources and company job boards.

All collectors yield the Job dataclass supplied by bot.py. They only read
public career-site information; no authentication, browser scraping, or
paid search APIs are used.
"""
from __future__ import annotations

from html import unescape
import logging
import re
import time
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

LOG = logging.getLogger("internship-alerts")
HARDWARE_URL = (
    "https://raw.githubusercontent.com/Khushsj30/"
    "hardware-internships-2027/main/README.md"
)
APPLYGUY_URL = (
    "https://raw.githubusercontent.com/ApplyGuy/"
    "2027-Internships/main/data/internships.json"
)
WORKDAY_TERMS = (
    "firmware", "embedded", "hardware", "electrical",
    "silicon", "RTL",
)
WORKDAY_PAGES_PER_TERM = 1  # 20 jobs per page; targeted rather than exhaustive
WORKDAY_DETAIL_CAP = 5


def _get(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    response = session.get(url, timeout=(5, 12), **kwargs)
    response.raise_for_status()
    return response


def _plain(value: Any) -> str:
    text = unescape(str(value or ""))
    return re.sub(r"<[^>]+>", " ", text).strip()


def _location_parts(item: dict[str, Any]) -> str:
    if isinstance(item.get("location"), str):
        return item["location"]
    loc = item.get("location")
    if not isinstance(loc, dict):
        loc = item
    fields = [loc.get(k) for k in ("city", "state", "country")]
    country_code = loc.get("country_code")
    if not fields[-1] and country_code == "US":
        fields[-1] = "United States"
    return ", ".join(str(x) for x in fields if x)


def hardware_internships_jobs(session: requests.Session, Job: Any) -> Iterator[Any]:
    """Read only the maintained Internships markdown table, not New Grad."""
    response = _get(session, HARDWARE_URL)
    body = response.text
    start = "<!-- INTERNSHIPS:START -->"
    stop = "<!-- INTERNSHIPS:END -->"
    if start not in body or stop not in body:
        raise ValueError("Hardware internship table markers missing")
    section = body.split(start, 1)[1].split(stop, 1)[0]
    for line in section.splitlines():
        if not line.startswith("| "):
            continue
        columns = [s.strip() for s in line.strip().strip("|").split("|")]
        if len(columns) != 5:
            continue
        company, title, location, posted, apply_link = columns
        match = re.search(r"\[Apply\]\((https?://[^)\s]+)\)", apply_link)
        if not match or title in ("Role", "") or company in ("Company", ""):
            continue
        url = unescape(match.group(1))
        posted = posted if re.fullmatch(r"\d{4}-\d{2}-\d{2}", posted) else ""
        yield Job("Hardware 2027", url, company, title, location, url, posted)


def applyguy_jobs(session: requests.Session, Job: Any) -> Iterator[Any]:
    """Use the original employer application link, never the ApplyGuy gateway."""
    data = _get(session, APPLYGUY_URL).json()
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("Unexpected ApplyGuy JSON feed")
    for item in jobs:
        if not isinstance(item, dict):
            continue
        url = str(item.get("listingUrl") or item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not (url.startswith("https://") and title):
            continue
        posted = str(item.get("posted") or "")
        posted = posted if re.fullmatch(r"\d{4}-\d{2}-\d{2}", posted) else ""
        yield Job(
            "ApplyGuy 2027",
            str(item.get("id") or url),
            str(item.get("company") or "Unknown"),
            title,
            str(item.get("location") or ""),
            url, posted,
            str(item.get("season") or ""),
        )


def workable_jobs(
    session: requests.Session, company: str, slug: str, Job: Any
) -> Iterator[Any]:
    """Workable's public, read-only careers widget (no HR API token)."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", slug):
        raise ValueError("Invalid Workable board identifier")
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    data = _get(session, url, params={"details": "true"}).json()
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("Unexpected Workable widget data")
    for item in jobs:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        job_url = str(
            item.get("url")
            or f"https://apply.workable.com/{slug}/j/{item.get('shortcode')}"
        )
        if not title or not job_url.startswith("https://"):
            continue
        location = _location_parts(item)
        extra = [
            _location_parts(loc) for loc in (item.get("locations") or [])
            if isinstance(loc, dict)
        ]
        location = "; ".join(dict.fromkeys(x for x in [location] + extra if x))
        yield Job(
            "Workable", str(item.get("shortcode") or job_url),
            company, title, location, job_url,
            str(item.get("published_on") or ""),
            description=_plain(item.get("description")),
        )


def _workday_board(board_url: str) -> tuple[str, str, str]:
    """Derive only from an explicitly configured public careers URL."""
    parsed = urlparse(board_url)
    host = parsed.netloc.lower()
    if (parsed.scheme != "https"
            or not host.endswith(".myworkdayjobs.com")
            or not re.fullmatch(r"[a-z0-9.-]+", host)):
        raise ValueError("Workday board must be an HTTPS myworkdayjobs.com URL")
    paths = [p for p in parsed.path.split("/") if p]
    if paths and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", paths[0]):
        paths.pop(0)
    if not paths:
        raise ValueError("Workday board site name missing")
    return host, host.split(".")[0], paths[0]


def workday_jobs(
    session: requests.Session, company: str, board_url: str, Job: Any
) -> Iterator[Any]:
    """Bounded searches against a public Workday careers site's CXS endpoint.

    Uses narrow search terms and up to two pages per term. Workday does NOT
    publish a stable public API; sites may reject or change these requests.
    """
    host, tenant, site = _workday_board(board_url)
    endpoint = f"https://{host}/wday/cxs/{tenant}/{site}"
    found: dict[str, dict[str, Any]] = {}
    for term in WORKDAY_TERMS:
        for page in range(WORKDAY_PAGES_PER_TERM):
            response = session.post(
                f"{endpoint}/jobs",
                json={
                    "appliedFacets": {}, "limit": 20,
                    "offset": page * 20, "searchText": term,
                },
                timeout=(5, 18),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            listings = data.get("jobPostings") if isinstance(data, dict) else None
            if not isinstance(listings, list):
                raise ValueError("Unexpected Workday jobs data")
            for item in listings:
                path = str(item.get("externalPath") or "")
                if path.startswith("/job/"):
                    found.setdefault(path, item)
            if len(listings) < 20:
                break
            time.sleep(0.12)  # Don't hammer a company's career site

    detail_reads = 0
    for path, item in found.items():
        title = str(item.get("title") or "")
        if not title:
            continue
        location = str(item.get("locationsText") or item.get("location") or "")
        description = ""
        posted = ""
        # Only fetch details for internship-like titles likely to be relevant.
        if (detail_reads < WORKDAY_DETAIL_CAP
                and re.search(r"intern|co.op|student engineer", title, re.I)
                and re.search(
                    r"firmware|embedded|hardware|electrical|silicon|"
                    r"software|systems|RTL|ASIC|chip|computer", title, re.I
                )):
            try:
                details = _get(session, f"{endpoint}{path}").json()
                info = details.get("jobPostingInfo") or {}
                description = _plain(info.get("jobDescription"))
                posted = str(info.get("startDate") or "")
                if info.get("location"):
                    location = str(info["location"])
                country = (info.get("country") or {}).get("descriptor")
                if country and country.lower() not in location.lower():
                    location = f"{location}, {country}"
                detail_reads += 1
            except (requests.RequestException, ValueError, TypeError) as exc:
                LOG.info("Workday job detail unavailable: %s", exc)
                detail_reads += 1
        # URL points to the original company career site; no aggregator.
        url = f"https://{host}/{site}{path}"
        yield Job(
            "Workday", path, company, title, location, url,
            posted=posted, description=description,
        )
