const BASE = '';  // Vite proxy handles /api -> localhost:8050

export async function fetchDates(): Promise<string[]> {
  const res = await fetch(`${BASE}/api/dates`);
  return res.json();
}

export async function fetchRankings(date: string, topN = 100): Promise<any[]> {
  const res = await fetch(`${BASE}/api/rankings/${date}?top_n=${topN}`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function fetchTickerDetail(ticker: string, date: string): Promise<any> {
  const res = await fetch(`${BASE}/api/ticker/${ticker}?date=${date}`);
  return res.json();
}

export async function fetchCRTResolutions(): Promise<any[]> {
  const res = await fetch(`${BASE}/api/crt/resolutions`);
  return res.json();
}

export async function fetchShadowPerformance(): Promise<any[]> {
  const res = await fetch(`${BASE}/api/shadow_performance`);
  return res.json();
}

export async function fetchBioshortVerdict(): Promise<any> {
  const res = await fetch(`${BASE}/api/bioshort/verdict`);
  return res.json();
}

export async function fetchBioshortReport(): Promise<any> {
  const res = await fetch(`${BASE}/api/bioshort/report`);
  return res.json();
}

export async function fetchBioshortWatch(): Promise<any> {
  const res = await fetch(`${BASE}/api/bioshort/watch`);
  return res.json();
}

export async function fetchPositions(date: string): Promise<any[]> {
  const res = await fetch(`${BASE}/api/positions/${date}`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}
