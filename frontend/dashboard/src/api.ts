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

export async function fetchTierBucketHeatmap(date: string): Promise<any> {
  const res = await fetch(`${BASE}/api/tier_bucket_heatmap/${date}`);
  return res.json();
}

export async function fetchHeraldHealth(): Promise<any> {
  const res = await fetch(`${BASE}/api/herald/health`);
  return res.json();
}

export async function fetchHeraldReleases(date: string): Promise<any[]> {
  const res = await fetch(`${BASE}/api/herald/releases/${date}`);
  return res.json();
}

export async function fetchHeraldClassified(date: string): Promise<any[]> {
  const res = await fetch(`${BASE}/api/herald/classified/${date}`);
  return res.json();
}

export async function fetchAACTTrials(ticker: string): Promise<any> {
  const res = await fetch(`${BASE}/api/aact/${ticker}`);
  return res.json();
}

export async function fetchPurpleBook(ticker: string, date: string): Promise<any> {
  const res = await fetch(`${BASE}/api/purple_book/${ticker}?date=${date}`);
  return res.json();
}

export async function fetchDealComps(ticker: string, date: string): Promise<any> {
  const res = await fetch(`${BASE}/api/deal_comps/${ticker}?date=${date}`);
  return res.json();
}

export async function fetchEventPremiumDecomp(date: string): Promise<any> {
  const res = await fetch(`${BASE}/api/event_premium_decomp/${date}`);
  return res.json();
}

export async function fetchPositions(date: string): Promise<any[]> {
  const res = await fetch(`${BASE}/api/positions/${date}`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function fetchCoinvestShadowHistory(): Promise<any[]> {
  const res = await fetch(`${BASE}/api/coinvest_shadow/history`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function fetchCoinvestShadowLatest(): Promise<any> {
  const res = await fetch(`${BASE}/api/coinvest_shadow/latest`);
  return res.json();
}

export async function fetchPostPromotionMonitorLatest(): Promise<any> {
  const res = await fetch(`${BASE}/api/post_promotion_monitor/latest`);
  return res.json();
}

export async function fetchPostPromotionMonitor(): Promise<any[]> {
  const res = await fetch(`${BASE}/api/post_promotion_monitor`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function fetchRegimeShadowHistory(): Promise<any[]> {
  const res = await fetch(`${BASE}/api/regime_shadow/history`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function fetchRegimeShadowLatest(): Promise<any> {
  const res = await fetch(`${BASE}/api/regime_shadow/latest`);
  return res.json();
}

export async function fetchConstructionV2Performance(): Promise<any[]> {
  const res = await fetch(`${BASE}/api/construction_v2/performance`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function fetchTimingHazardLatest(): Promise<any> {
  const res = await fetch(`${BASE}/api/timing_hazard/latest`);
  return res.json();
}

export async function fetchTimingHazardCalibration(): Promise<any[]> {
  const res = await fetch(`${BASE}/api/timing_hazard/calibration`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function fetchEventQualityShadowLatest(): Promise<any> {
  const res = await fetch(`${BASE}/api/event_quality_shadow/latest`);
  return res.json();
}
