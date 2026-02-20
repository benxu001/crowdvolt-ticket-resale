// ============================================================
// CONFIG - Replace these with your Supabase project values
// The anon key is safe to expose (read-only via Row-Level Security)
// ============================================================
const SUPABASE_URL = 'https://skoxrmbjxshqgsqhrjuy.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNrb3hybWJqeHNocWdzcWhyanV5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzEyODg0ODAsImV4cCI6MjA4Njg2NDQ4MH0.rpHrh6SBpldn9UQhPhl8PQlZnBjAWdTVe-5El4W-VbU';

// ============================================================
// Initialize Supabase client
// ============================================================
const db = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// ============================================================
// State
// ============================================================
let allEvents = [];
let currentChart = null;
let currentSlug = null;
let currentRange = 'all';

// ============================================================
// Init
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  loadEvents();
  setupTabs();
  setupBackButton();
  setupTimeFilters();
  setupSearch();
  setupDateFilters();
  setupVenueFilter();
});

// ============================================================
// Load events from Supabase
// ============================================================
async function loadEvents() {
  const loading = document.getElementById('loading');
  loading.style.display = 'block';

  try {
    // Fetch all events ordered by date
    const { data: events, error } = await db
      .from('events')
      .select('*')
      .order('event_date', { ascending: true });

    if (error) throw error;

    // Get the latest GA snapshot for each event to show on cards.
    // We fetch the most recent snapshot per event_slug for "General Admission".
    const slugs = events.map(e => e.slug);
    let snapshotMap = {};

    if (slugs.length > 0) {
      // Fetch the latest snapshot per event (ordered desc, we pick first per slug)
      const { data: snapshots } = await db
        .from('snapshots')
        .select('event_slug, lowest_ask, highest_bid, timestamp')
        .eq('ticket_type', 'General Admission')
        .in('event_slug', slugs)
        .order('timestamp', { ascending: false });

      if (snapshots) {
        for (const s of snapshots) {
          // Keep only the first (most recent) per slug
          if (!snapshotMap[s.event_slug]) {
            snapshotMap[s.event_slug] = s;
          }
        }
      }
    }

    allEvents = events.map(e => ({
      ...e,
      latest_ask: snapshotMap[e.slug]?.lowest_ask || null,
      latest_bid: snapshotMap[e.slug]?.highest_bid || null,
    }));

    populateVenueFilter();
    renderEventLists();
  } catch (err) {
    console.error('Failed to load events:', err);
    loading.textContent = 'Failed to load events. Check console for details.';
  }

  loading.style.display = 'none';
}

// ============================================================
// Render event lists (upcoming / past)
// ============================================================
function renderEventLists() {
  const searchInput = document.getElementById('search-input');
  const query = (searchInput?.value || '').toLowerCase();
  const now = new Date();

  const dateFilter = document.getElementById('date-filter')?.value || '';
  const venueFilter = document.getElementById('venue-filter')?.value || '';

  const filtered = allEvents.filter(e => {
    if (query) {
      const match = (e.name || '').toLowerCase().includes(query)
        || (e.venue || '').toLowerCase().includes(query)
        || (e.slug || '').toLowerCase().includes(query);
      if (!match) return false;
    }
    if (dateFilter && e.event_date) {
      if (e.event_date.slice(0, 10) !== dateFilter) return false;
    }
    if (venueFilter && (e.venue || '') !== venueFilter) return false;
    return true;
  });

  const sortByPriceThenName = (a, b) => {
    // Same date group: highest ask first, then alphabetical
    const askA = a.latest_ask || 0;
    const askB = b.latest_ask || 0;
    if (askB !== askA) return askB - askA;
    return (a.name || a.slug).localeCompare(b.name || b.slug);
  };

  // An event moves to "past" at midnight EST the day after the event.
  // e.g. Feb 20 event becomes past at Feb 21 00:00 EST (Feb 21 05:00 UTC)
  function isPast(e) {
    if (!e.event_date) return false;
    const dateStr = e.event_date.slice(0, 10); // YYYY-MM-DD in UTC
    // Day after event at midnight EST = day after + 05:00 UTC
    const cutoff = new Date(dateStr + 'T05:00:00Z');
    cutoff.setUTCDate(cutoff.getUTCDate() + 1);
    return now >= cutoff;
  }

  const upcoming = filtered.filter(e => !isPast(e));
  upcoming.sort((a, b) => {
    const dateA = a.event_date || '';
    const dateB = b.event_date || '';
    if (dateA.slice(0, 10) !== dateB.slice(0, 10)) return dateA < dateB ? -1 : 1;
    return sortByPriceThenName(a, b);
  });

  const past = filtered.filter(e => isPast(e));
  past.sort((a, b) => {
    const dateA = a.event_date || '';
    const dateB = b.event_date || '';
    if (dateA.slice(0, 10) !== dateB.slice(0, 10)) return dateB < dateA ? -1 : 1; // most recent first
    return sortByPriceThenName(a, b);
  });

  renderCards('upcoming-events', upcoming);
  renderCards('past-events', past);

  if (upcoming.length === 0) {
    document.getElementById('upcoming-events').innerHTML =
      '<div class="empty-state">No upcoming events found.</div>';
  }
  if (past.length === 0) {
    document.getElementById('past-events').innerHTML =
      '<div class="empty-state">No past events yet.</div>';
  }
}

function renderCards(containerId, events) {
  const container = document.getElementById(containerId);
  container.innerHTML = events.map(e => `
    <div class="event-card" data-slug="${e.slug}">
      <h3>${escapeHtml(e.name || e.slug)}</h3>
      <div class="event-meta">
        <span class="venue">${escapeHtml(e.venue || 'TBA')}</span>
        ${e.event_date ? ' &middot; ' + formatDate(e.event_date) : ''}
      </div>
      <div class="price-row">
        <span class="price-ask">Ask: ${e.latest_ask ? '$' + e.latest_ask : '—'}</span>
        <span class="price-bid">Bid: ${e.latest_bid ? '$' + e.latest_bid : '—'}</span>
      </div>
    </div>
  `).join('');

  container.querySelectorAll('.event-card').forEach(card => {
    card.addEventListener('click', () => showEventDetail(card.dataset.slug));
  });
}

// ============================================================
// Event detail view
// ============================================================
async function showEventDetail(slug) {
  currentSlug = slug;
  const event = allEvents.find(e => e.slug === slug);
  if (!event) return;

  document.getElementById('event-list-view').style.display = 'none';
  document.getElementById('event-detail-view').style.display = 'block';
  document.getElementById('detail-title').textContent = event.name || event.slug;
  document.getElementById('detail-meta').textContent =
    `${event.venue || 'TBA'}${event.event_date ? ' \u00B7 ' + formatDate(event.event_date) : ''}`;
  document.getElementById('detail-link').href = event.url || '#';

  // Reset to "All Time" filter
  currentRange = 'all';
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.range === 'all');
  });

  await loadPriceChart(slug, 'all');
}

async function loadPriceChart(slug, range) {
  const detailLoading = document.getElementById('detail-loading');
  detailLoading.style.display = 'block';

  try {
    let query = db
      .from('snapshots')
      .select('timestamp, ticket_type, lowest_ask, highest_bid')
      .eq('event_slug', slug)
      .order('timestamp', { ascending: true });

    // Apply time filter
    if (range !== 'all') {
      const cutoff = getCutoffDate(range);
      query = query.gte('timestamp', cutoff.toISOString());
    }

    const { data: snapshots, error } = await query;
    if (error) throw error;

    const event = allEvents.find(e => e.slug === slug);
    renderChart(snapshots, event?.event_date);
  } catch (err) {
    console.error('Failed to load price data:', err);
  }

  detailLoading.style.display = 'none';
}

// ============================================================
// Chart rendering
// ============================================================
function renderChart(snapshots, eventDate) {
  if (currentChart) {
    currentChart.destroy();
    currentChart = null;
  }

  if (!snapshots || snapshots.length === 0) {
    const ctx = document.getElementById('price-chart').getContext('2d');
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.fillStyle = '#555';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No price data available yet', ctx.canvas.width / 2, ctx.canvas.height / 2);
    return;
  }

  // Group by ticket type, then build datasets
  // Primary focus: General Admission
  const gaSnapshots = snapshots.filter(s => s.ticket_type === 'General Admission');
  const otherTypes = [...new Set(snapshots.map(s => s.ticket_type))].filter(t => t !== 'General Admission');

  const datasets = [];

  // GA datasets (primary)
  if (gaSnapshots.length > 0) {
    datasets.push({
      label: 'GA Floor Price (Ask)',
      data: gaSnapshots.map(s => ({ x: new Date(s.timestamp), y: s.lowest_ask })),
      borderColor: '#ef4444',
      backgroundColor: 'rgba(239, 68, 68, 0.1)',
      borderWidth: 2,
      pointRadius: 2,
      tension: 0.3,
      fill: false,
    });
    datasets.push({
      label: 'GA Highest Bid',
      data: gaSnapshots.map(s => ({ x: new Date(s.timestamp), y: s.highest_bid })),
      borderColor: '#22c55e',
      backgroundColor: 'rgba(34, 197, 94, 0.1)',
      borderWidth: 2,
      pointRadius: 2,
      tension: 0.3,
      fill: false,
    });
  }

  // Other ticket types (secondary, dimmer colors)
  const colors = ['#60a5fa', '#f59e0b', '#a78bfa', '#ec4899'];
  otherTypes.forEach((type, i) => {
    const typeSnapshots = snapshots.filter(s => s.ticket_type === type);
    const color = colors[i % colors.length];
    datasets.push({
      label: `${type} Ask`,
      data: typeSnapshots.map(s => ({ x: new Date(s.timestamp), y: s.lowest_ask })),
      borderColor: color,
      borderWidth: 1.5,
      borderDash: [5, 3],
      pointRadius: 1,
      tension: 0.3,
      fill: false,
    });
  });

  const ctx = document.getElementById('price-chart').getContext('2d');
  currentChart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        annotation: eventDate ? {
          annotations: {
            eventStart: {
              type: 'line',
              xMin: new Date(eventDate.slice(0, 10) + 'T21:00:00-05:00'),
              xMax: new Date(eventDate.slice(0, 10) + 'T21:00:00-05:00'),
              borderColor: '#f59e0b',
              borderWidth: 2,
              borderDash: [6, 3],
              label: {
                display: true,
                content: 'Event Start',
                position: 'start',
                backgroundColor: 'rgba(245, 158, 11, 0.8)',
                color: '#000',
                font: { size: 11, weight: 'bold' },
              },
            },
          },
        } : {},
        legend: {
          labels: { color: '#aaa', font: { size: 12 } },
        },
        tooltip: {
          backgroundColor: '#222',
          titleColor: '#fff',
          bodyColor: '#ccc',
          borderColor: '#333',
          borderWidth: 1,
          callbacks: {
            label: ctx => `${ctx.dataset.label}: $${ctx.parsed.y ?? '—'}`,
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          time: {
            tooltipFormat: 'MMM d, h:mm a',
          },
          grid: { color: '#1a1a1a' },
          ticks: { color: '#666', maxTicksLimit: 12 },
        },
        y: {
          beginAtZero: false,
          grid: { color: '#1a1a1a' },
          ticks: {
            color: '#666',
            callback: val => '$' + val,
          },
          title: {
            display: true,
            text: 'Price ($)',
            color: '#666',
          },
        },
      },
    },
  });
}

// ============================================================
// UI Setup
// ============================================================
function setupTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      const target = tab.dataset.tab;
      document.getElementById('upcoming-events').style.display =
        target === 'upcoming' ? '' : 'none';
      document.getElementById('past-events').style.display =
        target === 'past' ? '' : 'none';
    });
  });
}

function setupBackButton() {
  document.getElementById('back-btn').addEventListener('click', () => {
    document.getElementById('event-detail-view').style.display = 'none';
    document.getElementById('event-list-view').style.display = 'block';
    if (currentChart) {
      currentChart.destroy();
      currentChart = null;
    }
  });
}

function setupTimeFilters() {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentRange = btn.dataset.range;
      if (currentSlug) {
        loadPriceChart(currentSlug, currentRange);
      }
    });
  });
}

function setupSearch() {
  const input = document.getElementById('search-input');
  if (!input) return;
  let debounceTimer;
  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => renderEventLists(), 200);
  });
}

function populateVenueFilter() {
  const select = document.getElementById('venue-filter');
  if (!select) return;
  const venues = [...new Set(allEvents.map(e => e.venue).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' })
  );
  select.innerHTML = '<option value="">All Venues</option>' +
    venues.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
}

function setupVenueFilter() {
  const select = document.getElementById('venue-filter');
  if (!select) return;
  select.addEventListener('change', () => renderEventLists());
}

function setupDateFilters() {
  const dateInput = document.getElementById('date-filter');
  const clearBtn = document.getElementById('date-clear');
  if (!dateInput || !clearBtn) return;

  dateInput.addEventListener('change', () => {
    clearBtn.style.display = dateInput.value ? 'inline-block' : 'none';
    renderEventLists();
  });

  clearBtn.addEventListener('click', () => {
    dateInput.value = '';
    clearBtn.style.display = 'none';
    renderEventLists();
  });
}

// ============================================================
// Helpers
// ============================================================
function getCutoffDate(range) {
  const now = new Date();
  const ms = {
    '1d': 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
    '1m': 30 * 24 * 60 * 60 * 1000,
  };
  return new Date(now.getTime() - ms[range]);
}

function formatDate(isoStr) {
  try {
    // Parse as UTC to avoid timezone shift (dates stored as midnight UTC)
    const d = new Date(isoStr);
    return d.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    });
  } catch {
    return isoStr;
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
