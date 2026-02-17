"""
CrowdVolt NYC Price Scraper

Fetches pricing data from individual CrowdVolt event pages and stores
hourly snapshots in Supabase. Reads the event list from the Supabase
events table (populated by discover.py).

Run hourly via GitHub Actions or manually:
    python scraper/scrape.py
"""

import os
import re
import json
import time
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {
    "User-Agent": "CrowdVoltNYCTracker/1.0 (personal portfolio project)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY = 1.5  # seconds between requests


def get_active_events():
    """Fetch all events from Supabase that haven't passed yet."""
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get events whose date is in the future or up to 1 day ago
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    result = (
        supabase.table("events")
        .select("slug, name, venue, event_date, url")
        .gte("event_date", cutoff)
        .execute()
    )

    # Also get events with null event_date (couldn't parse date during discovery)
    result_null = (
        supabase.table("events")
        .select("slug, name, venue, event_date, url")
        .is_("event_date", "null")
        .execute()
    )

    events = result.data + result_null.data
    print(f"Found {len(events)} active events to scrape")
    return events


def extract_pricing_from_page(html):
    """
    Extract pricing data from a CrowdVolt event page.

    The page uses Next.js RSC streaming with escaped JSON (\\") in the
    payload. Pricing fields include:
      - \\"min_ask\\", \\"max_bid\\" (top-level summary)
      - Per-ticket-type: \\"highest_bid_price\\", \\"lowest_ask_price\\", \\"name\\"
    """
    ticket_types = {}

    # Strategy 1: Per-ticket-type pricing from the tt_data.types array
    # Structure: \"types\":[{\"name\":\"GA\",...,\"highest_bid_price\":N,...,\"lowest_ask_price\":N,...},{...}]
    tt_section = re.search(r'\\"types\\":\[(\{.*?\})\]', html)
    if tt_section:
        # Split into individual ticket type objects
        for chunk in tt_section.group(1).split('},{'):
            name_m = re.search(r'\\"name\\":\\"([^\\]+)\\"', chunk)
            ask_m = re.search(r'\\"lowest_ask_price\\":(\d+(?:\.\d+)?|null)', chunk)
            bid_m = re.search(r'\\"highest_bid_price\\":(\d+(?:\.\d+)?|null)', chunk)

            if name_m and (ask_m or bid_m):
                name = name_m.group(1)
                ask_val = ask_m.group(1) if ask_m else "null"
                bid_val = bid_m.group(1) if bid_m else "null"
                ticket_types[name] = {
                    "lowest_ask": float(ask_val) if ask_val != "null" else None,
                    "highest_bid": float(bid_val) if bid_val != "null" else None,
                }

    # Strategy 2: Fall back to top-level min_ask / max_bid
    if not ticket_types:
        min_ask_match = re.search(r'\\"min_ask\\":(\d+(?:\.\d+)?)', html)
        max_bid_match = re.search(r'\\"max_bid\\":(\d+(?:\.\d+)?)', html)
        min_ask_type_match = re.search(r'\\"min_ask_type\\":\\"([^\\]+)\\"', html)

        ticket_type_name = (
            min_ask_type_match.group(1) if min_ask_type_match else "General Admission"
        )
        lowest_ask = float(min_ask_match.group(1)) if min_ask_match else None
        highest_bid = float(max_bid_match.group(1)) if max_bid_match else None

        if lowest_ask is not None or highest_bid is not None:
            ticket_types[ticket_type_name] = {
                "lowest_ask": lowest_ask,
                "highest_bid": highest_bid,
            }

    metadata = {}
    return ticket_types, metadata


def scrape_event(url):
    """Fetch an event page and extract pricing data."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return extract_pricing_from_page(resp.text)
    except requests.RequestException as e:
        print(f"  HTTP error for {url}: {e}")
        return {}, {}


def save_snapshots(supabase, snapshots):
    """Batch insert snapshots into Supabase."""
    if not snapshots:
        return

    print(f"Inserting {len(snapshots)} snapshot rows...")

    # Insert in batches of 100
    batch_size = 100
    for i in range(0, len(snapshots), batch_size):
        batch = snapshots[i : i + batch_size]
        try:
            supabase.table("snapshots").insert(batch).execute()
        except Exception as e:
            print(f"  Warning: Failed to insert batch {i // batch_size}: {e}")


def main():
    print("=== CrowdVolt NYC Price Scraper ===")
    now = datetime.now(timezone.utc)
    print(f"Time: {now.isoformat()}")

    events = get_active_events()
    if not events:
        print("No active events found. Run discover.py first.")
        return

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    timestamp = now.isoformat()
    all_snapshots = []
    success_count = 0
    skip_count = 0

    for i, event in enumerate(events):
        slug = event["slug"]
        url = event["url"]
        print(f"[{i + 1}/{len(events)}] Scraping {slug}...")

        ticket_types, metadata = scrape_event(url)

        if not ticket_types:
            print(f"  No pricing data found")
            skip_count += 1
        else:
            for tt_name, prices in ticket_types.items():
                all_snapshots.append(
                    {
                        "event_slug": slug,
                        "timestamp": timestamp,
                        "ticket_type": tt_name,
                        "lowest_ask": prices["lowest_ask"],
                        "highest_bid": prices["highest_bid"],
                    }
                )
            success_count += 1
            print(
                f"  Found {len(ticket_types)} ticket type(s): "
                + ", ".join(
                    f"{k}: ask=${v['lowest_ask']} bid=${v['highest_bid']}"
                    for k, v in ticket_types.items()
                )
            )

        # Rate limit
        if i < len(events) - 1:
            time.sleep(REQUEST_DELAY)

    save_snapshots(supabase, all_snapshots)

    print(f"\nDone! {success_count} events scraped, {skip_count} skipped (no data)")


if __name__ == "__main__":
    main()
