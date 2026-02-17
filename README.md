# NYC Ticket Resale Tracker

A fully automated pipeline that tracks hourly resale ticket prices for New York City events on [CrowdVolt](https://www.crowdvolt.com), with a live dashboard hosted on GitHub Pages.

**[View Live Dashboard](https://benxu001.github.io/crowdvolt-ticket-resale/)**

---

## Overview

CrowdVolt is a ticket resale marketplace where prices fluctuate based on supply and demand. This project captures those price movements over time, enabling analysis of pricing trends for NYC concerts, festivals, and live events.

### How It Works

```
CrowdVolt Sitemap ──► discover.py ──► Supabase (events table)
                                            │
CrowdVolt Event Pages ──► scrape.py ──► Supabase (snapshots table)
                                            │
                                     GitHub Pages Dashboard
                                     (reads via Supabase anon key)
```

1. **Discovery** (`discover.py`) — Runs daily at midnight EST. Fetches the CrowdVolt sitemap, visits each event page, and filters for New York events by extracting the `area_name` field from the Next.js RSC payload. Upserts event metadata (name, venue, date, URL) into Supabase.

2. **Price Scraping** (`scrape.py`) — Runs every hour. For each active event, fetches the CrowdVolt page and extracts per-ticket-type pricing (lowest ask, highest bid) from the RSC payload. Stores each data point as a timestamped snapshot in Supabase.

3. **Dashboard** (`docs/`) — A static site served via GitHub Pages. Reads directly from Supabase using the public anon key (read-only via Row-Level Security). Displays event cards with latest prices, search/filter controls, and interactive Chart.js price history charts.

---

## Project Structure

```
├── .github/workflows/
│   ├── discover.yml      # Daily event discovery (midnight EST)
│   ├── scrape.yml        # Hourly price scraping
│   └── pages.yml         # Deploy dashboard to GitHub Pages
├── scraper/
│   ├── discover.py       # Event discovery script
│   ├── scrape.py         # Price scraping script
│   └── requirements.txt  # Python dependencies
├── docs/
│   ├── index.html        # Dashboard HTML
│   ├── style.css         # Dashboard styles (dark theme)
│   └── app.js            # Dashboard logic (Supabase client, Chart.js)
├── supabase_setup.sql    # Database schema & RLS policies
└── README.md
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Data storage | [Supabase](https://supabase.com) (PostgreSQL) |
| Scraping | Python 3.12, `requests`, regex on Next.js RSC payload |
| Automation | GitHub Actions (cron schedules) |
| Dashboard | Vanilla HTML/CSS/JS, [Chart.js](https://www.chartjs.org/) |
| Hosting | GitHub Pages |

---

## Database Schema

**`events`** — One row per CrowdVolt event

| Column | Type | Description |
|--------|------|-------------|
| `slug` | text (unique) | CrowdVolt URL slug (e.g. `jamie-jones-knockdown-center-fri-feb-20-new-york`) |
| `name` | text | Event/artist name |
| `venue` | text | Venue name |
| `event_date` | timestamptz | Event date |
| `url` | text | Full CrowdVolt URL |

**`snapshots`** — Hourly price data points

| Column | Type | Description |
|--------|------|-------------|
| `event_slug` | text (FK) | References `events.slug` |
| `timestamp` | timestamptz | When the price was captured |
| `ticket_type` | text | e.g. "General Admission", "VIP" |
| `lowest_ask` | numeric | Lowest asking price |
| `highest_bid` | numeric | Highest bid price |

---

## Setup

### Prerequisites

- A [Supabase](https://supabase.com) project (free tier works)
- A GitHub repository with Pages enabled

### 1. Database Setup

Run `supabase_setup.sql` in your Supabase SQL Editor. This creates both tables, indexes, and Row-Level Security policies (public read, service-role write).

### 2. GitHub Secrets

Add these secrets in your repo settings (**Settings > Secrets and variables > Actions**):

| Secret | Value |
|--------|-------|
| `SUPABASE_URL` | Your Supabase project URL (e.g. `https://xxx.supabase.co`) |
| `SUPABASE_SERVICE_KEY` | Your Supabase service role key (from Settings > API) |

### 3. Dashboard Configuration

In `docs/app.js`, update the two constants at the top with your Supabase project URL and **anon** key (safe to expose publicly — read-only via RLS):

```js
const SUPABASE_URL = 'https://your-project.supabase.co';
const SUPABASE_ANON_KEY = 'your-anon-key';
```

### 4. Enable GitHub Pages

Go to **Settings > Pages** and set the source to **GitHub Actions**.

### 5. Run the Pipelines

Trigger the workflows manually for the first run:

1. **Actions > Discover NYC Events > Run workflow** — populates the events table
2. **Actions > Scrape NYC Prices > Run workflow** — captures the first price snapshot
3. **Actions > Deploy Dashboard > Run workflow** — deploys the dashboard

After that, everything runs automatically on schedule.

---

## Dashboard Features

- **Event cards** with latest ask/bid prices, sorted by date then price
- **Search** by event name, artist, or venue
- **Date filter** to view events on a specific date
- **Upcoming / Past** tabs
- **Interactive price charts** (Chart.js) with time range filters (1 Day, 1 Week, 1 Month, All Time)
- **Per-ticket-type tracking** — GA shown as primary lines, other types (VIP, etc.) as dashed secondary lines
- **Dark theme** UI
- **Responsive** layout for mobile

---

## Technical Notes

### CrowdVolt Data Extraction

CrowdVolt uses Next.js App Router with React Server Components (RSC). The HTML contains an RSC streaming payload with escaped JSON data. Key fields are extracted via regex patterns matching escaped quotes:

```python
# Example: extracting area_name from RSC payload
RE_AREA = re.compile(r'\\"area_name\\":\\"([^\\]+)\\"')
```

This approach bypasses the need for headless browser rendering. Standard HTTP requests with `requests` are used instead of Playwright, which is blocked by Cloudflare Turnstile on CrowdVolt.

### Pricing Data Accuracy

Prices are extracted from CrowdVolt's RSC payload summary fields (`lowest_ask_price`, `highest_bid_price`) rather than individual listing prices. These summary values may differ slightly from what CrowdVolt displays on its frontend — for example, the RSC payload might report a lowest ask of $99 while the UI shows $102 as the cheapest visible listing. The RSC data also includes ticket types like multi-day passes that CrowdVolt may not surface in its UI. Despite these minor discrepancies, the summary fields accurately capture pricing trends over time, which is the primary goal of this project.

### Rate Limiting

Both scrapers include delays between requests (1.0s for discovery, 1.5s for pricing) and identify themselves with a custom User-Agent string.

---

## Scheduling

| Workflow | Schedule | Description |
|----------|----------|-------------|
| Discover NYC Events | `0 5 * * *` (midnight EST) | Finds new events from sitemap |
| Scrape NYC Prices | `0 * * * *` (hourly) | Captures price snapshots |
| Deploy Dashboard | On push to `docs/**` | Deploys updated dashboard |

> **Note:** GitHub Actions cron schedules may have 5-15 minute delays. Workflows are automatically disabled after 60 days of repo inactivity.

---

## License

This project is for educational and portfolio purposes. Event data is sourced from [CrowdVolt](https://www.crowdvolt.com).
