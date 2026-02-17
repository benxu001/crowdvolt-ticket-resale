"""
CrowdVolt NYC Event Discovery Script

Fetches event slugs from the CrowdVolt sitemap, then visits each event
page to extract metadata from the Next.js RSC payload. Filters for
New York events and upserts them into Supabase.

Run daily via GitHub Actions or manually:
    python scraper/discover.py
"""

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests
from supabase import create_client

SITEMAP_URL = "https://www.crowdvolt.com/sitemap.xml"
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {
    "User-Agent": "CrowdVoltNYCTracker/1.0 (personal portfolio project)",
    "Accept": "text/html,application/xhtml+xml,application/xml",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY = 1.0  # seconds between requests

# Patterns for escaped JSON in Next.js RSC payload
# Data appears as: \"area_name\":\"New York\",\"name\":\"Artist\",...
RE_AREA = re.compile(r'\\"area_name\\":\\"([^\\]+)\\"')
RE_NAME = re.compile(r'\\"area_name\\":\\"[^\\]+\\",\\"name\\":\\"([^\\]+)\\"')
RE_VENUE = re.compile(r'\\"venue\\":\\"([^\\]+)\\"')
RE_DATE = re.compile(r'\\"date\\":\\"([^\\]+)\\"')


def fetch_event_slugs():
    """Fetch all event slugs from the CrowdVolt sitemap."""
    print(f"Fetching sitemap from {SITEMAP_URL}...")
    resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    slugs = []
    for url_elem in root.findall("s:url/s:loc", ns):
        loc = url_elem.text
        if loc and "/event/" in loc:
            slug = loc.split("/event/")[-1].strip("/")
            if slug:
                slugs.append(slug)

    print(f"Found {len(slugs)} event URLs in sitemap")
    return slugs


def extract_event_data(html):
    """Extract event metadata from the Next.js RSC payload.

    The RSC payload contains escaped JSON with event data like:
    \\"area_name\\":\\"New York\\",\\"name\\":\\"Jamie Jones\\",...
    """
    area_match = RE_AREA.search(html)
    name_match = RE_NAME.search(html)

    area_name = area_match.group(1) if area_match else None
    name = name_match.group(1) if name_match else None

    # Get venue and date from <title> as primary source (clean, unescaped)
    # Format: "Artist City tickets - Venue - Date | CrowdVolt"
    title_match = re.search(r'<title>([^<]+)</title>', html)
    title = title_match.group(1) if title_match else ""
    venue = None
    date_str = None

    if " tickets - " in title:
        after = title.split(" tickets - ", 1)[1]
        parts = after.split(" - ")
        if len(parts) >= 2:
            # Date is always the last part; venue is everything before it
            date_str = parts[-1].replace(" | CrowdVolt", "").strip()
            venue = " - ".join(parts[:-1]).strip()
        else:
            venue = parts[0].replace(" | CrowdVolt", "").strip()

    # Fallback to RSC payload for venue/date
    if not venue:
        v = RE_VENUE.search(html)
        if v:
            venue = v.group(1)
    if not date_str:
        d = RE_DATE.search(html)
        if d:
            date_str = d.group(1)

    # Fallback name from title
    if not name and " tickets - " in title:
        name = title.split(" tickets - ")[0].rsplit(" ", 1)[0]

    return {
        "area_name": area_name,
        "name": name,
        "venue": venue,
        "date": date_str,
    }


def parse_display_date(date_str):
    """Parse display date like 'Fri, February 20' into ISO format."""
    if not date_str:
        return None

    try:
        cleaned = re.sub(r"^[A-Za-z]+,\s*", "", date_str)
        cleaned = cleaned.replace("•", "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)

        for fmt in ["%B %d %I%p", "%B %d %I:%M%p", "%B %d"]:
            try:
                dt = datetime.strptime(cleaned, fmt)
                now = datetime.now(timezone.utc)
                dt = dt.replace(year=now.year)
                if dt.month < now.month:
                    dt = dt.replace(year=now.year + 1)
                return dt.isoformat()
            except ValueError:
                continue
    except Exception:
        pass
    return None


def discover_events():
    """Discover NYC events: sitemap -> fetch each page -> filter by area_name."""
    slugs = fetch_event_slugs()

    nyc_events = []
    other_count = 0

    for i, slug in enumerate(slugs):
        url = f"https://www.crowdvolt.com/event/{slug}"
        print(f"[{i + 1}/{len(slugs)}] {slug}...", end=" ")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = extract_event_data(resp.text)

            if data["area_name"] == "New York":
                event = {
                    "slug": slug,
                    "name": data["name"] or slug,
                    "venue": data["venue"] or "",
                    "event_date": parse_display_date(data["date"]),
                    "url": url,
                }
                nyc_events.append(event)
                print(f"NYC -> {data['name']} @ {data['venue']}")
            else:
                other_count += 1
                print(f"skip ({data['area_name'] or 'unknown'})")
        except requests.RequestException as e:
            print(f"HTTP error: {e}")
            other_count += 1

        if i < len(slugs) - 1:
            time.sleep(REQUEST_DELAY)

    print(f"\nDiscovered {len(nyc_events)} NYC events ({other_count} other cities skipped)")
    return nyc_events


def upsert_to_supabase(events):
    """Upsert discovered events into Supabase."""
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    print(f"Upserting {len(events)} events to Supabase...")
    success_count = 0

    for event in events:
        try:
            row = {
                "slug": event["slug"],
                "name": event["name"],
                "venue": event["venue"],
                "url": event["url"],
            }
            if event["event_date"]:
                row["event_date"] = event["event_date"]

            supabase.table("events").upsert(
                row, on_conflict="slug"
            ).execute()
            success_count += 1
        except Exception as e:
            print(f"  Warning: Failed to upsert {event['slug']}: {e}")

    print(f"Successfully upserted {success_count}/{len(events)} events")


def main():
    print("=== CrowdVolt NYC Event Discovery ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    events = discover_events()

    if not events:
        print("ERROR: No events discovered. Exiting.")
        return

    upsert_to_supabase(events)
    print("Done!")


if __name__ == "__main__":
    main()
