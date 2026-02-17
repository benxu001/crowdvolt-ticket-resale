"""
CrowdVolt NYC Event Discovery Script

Uses Playwright to load the CrowdVolt homepage with the New York filter,
scrolls to load all events, and upserts them into Supabase.

Run daily via GitHub Actions or manually:
    python scraper/discover.py
"""

import os
import re
import json
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from supabase import create_client

CROWDVOLT_URL = "https://www.crowdvolt.com/"
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def discover_events():
    """Load CrowdVolt homepage, select NY filter, scroll and extract all events."""
    events = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="CrowdVoltNYCTracker/1.0 (personal portfolio project)"
        )

        print("Navigating to CrowdVolt...")
        page.goto(CROWDVOLT_URL, wait_until="domcontentloaded", timeout=60000)
        # Wait for event cards to appear on the page
        page.wait_for_selector('a[href^="/event/"]', timeout=30000)

        # The homepage shows "Browse Events in New York" with city filters.
        # "New York" appears to be the default selection (underlined in screenshot).
        # Click it explicitly to be safe.
        try:
            ny_filter = page.locator("text=New York").first
            ny_filter.click()
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Warning: Could not click New York filter: {e}")
            print("Proceeding with default view...")

        # Scroll down to load all events (infinite scroll)
        print("Scrolling to load all events...")
        prev_count = 0
        stale_rounds = 0
        max_stale_rounds = 5

        while stale_rounds < max_stale_rounds:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

            # Count current event cards
            cards = page.locator('a[href^="/event/"]').all()
            current_count = len(cards)
            print(f"  Found {current_count} event links...")

            if current_count == prev_count:
                stale_rounds += 1
            else:
                stale_rounds = 0
            prev_count = current_count

        print(f"Finished scrolling. Total event links found: {prev_count}")

        # Extract event data from cards
        cards = page.locator('a[href^="/event/"]').all()
        seen_slugs = set()

        for card in cards:
            try:
                href = card.get_attribute("href")
                if not href or "/event/" not in href:
                    continue

                slug = href.replace("/event/", "").strip("/")
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                # Try to extract text content from the card
                text = card.inner_text()
                lines = [line.strip() for line in text.split("\n") if line.strip()]

                # Parse card text - typical format from screenshot:
                # "Bedouin"
                # "Fri, February 20 • 10PM"
                # "Capitale"
                # "From $101"
                name = lines[0] if len(lines) > 0 else slug
                date_str = lines[1] if len(lines) > 1 else ""
                venue = lines[2] if len(lines) > 2 else ""

                # Parse the date string (e.g., "Fri, February 20 • 10PM")
                event_date = parse_event_date(date_str)

                events.append({
                    "slug": slug,
                    "name": name,
                    "venue": venue,
                    "event_date": event_date,
                    "url": f"https://www.crowdvolt.com/event/{slug}",
                })
            except Exception as e:
                print(f"  Warning: Failed to parse card: {e}")
                continue

        browser.close()

    print(f"Extracted {len(events)} unique events")
    return events


def parse_event_date(date_str):
    """Parse date string like 'Fri, February 20 • 10PM' into ISO format."""
    if not date_str:
        return None

    try:
        # Remove day-of-week prefix and bullet separator
        # "Fri, February 20 • 10PM" -> "February 20 10PM"
        cleaned = re.sub(r"^[A-Za-z]+,\s*", "", date_str)
        cleaned = cleaned.replace("•", "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)

        # Try parsing with time
        # "February 20 10PM" or "February 20 10:00PM"
        for fmt in ["%B %d %I%p", "%B %d %I:%M%p", "%B %d"]:
            try:
                dt = datetime.strptime(cleaned, fmt)
                # Assume current year or next year if month has passed
                now = datetime.now()
                dt = dt.replace(year=now.year)
                if dt.month < now.month:
                    dt = dt.replace(year=now.year + 1)
                return dt.isoformat()
            except ValueError:
                continue

        print(f"  Warning: Could not parse date '{date_str}'")
        return None
    except Exception:
        return None


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
