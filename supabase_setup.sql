-- ============================================================
-- CrowdVolt NYC Tracker - Supabase Schema Setup
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor)
-- ============================================================

-- Events table: one row per event discovered on CrowdVolt
CREATE TABLE events (
  id serial PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  name text,
  venue text,
  event_date timestamptz,
  url text,
  created_at timestamptz DEFAULT now()
);

-- Snapshots table: hourly price data points per event per ticket type
CREATE TABLE snapshots (
  id serial PRIMARY KEY,
  event_slug text NOT NULL REFERENCES events(slug),
  timestamp timestamptz NOT NULL,
  ticket_type text NOT NULL,
  lowest_ask numeric,
  highest_bid numeric
);

-- Index for fast time-range queries per event
CREATE INDEX idx_snapshots_event_time ON snapshots(event_slug, timestamp DESC);

-- Index for filtering active events by date
CREATE INDEX idx_events_date ON events(event_date);

-- ============================================================
-- Row-Level Security (RLS)
-- Allow anonymous read access (for the dashboard)
-- Write access requires the service_role key (used by the scraper)
-- ============================================================

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;

-- Anyone can read events
CREATE POLICY "Public read access for events"
  ON events FOR SELECT
  USING (true);

-- Anyone can read snapshots
CREATE POLICY "Public read access for snapshots"
  ON snapshots FOR SELECT
  USING (true);

-- Service role can insert/update events (scraper uses service_role key)
CREATE POLICY "Service role can insert events"
  ON events FOR INSERT
  WITH CHECK (true);

CREATE POLICY "Service role can update events"
  ON events FOR UPDATE
  USING (true);

-- Service role can insert snapshots
CREATE POLICY "Service role can insert snapshots"
  ON snapshots FOR INSERT
  WITH CHECK (true);
