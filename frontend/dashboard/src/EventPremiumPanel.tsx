import { useEffect, useState } from 'react';
import { fetchEventPremiumDecomp, fetchOptionsQCSummary } from './api';

interface EPDName {
  ticker: string;
  epd_event_premium_ratio: number | null;
  epd_term_slope_z: number | null;
  epd_skew_richness_z: number | null;
  epd_iv_momentum: number | null;
  epd_iv_ramping: boolean;
  epd_iv_crushing: boolean;
  epd_iv_per_catalyst_day: number | null;
  epd_catalyst_proximity_bucket: string | null;
  epd_surface_regime: string;
  epd_quality: string;
  epd_event_premium_ratio_z: number | null;
  epd_iv_momentum_z: number | null;
  epd_implied_vs_realized_ratio: number | null;
  epd_mispricing_direction: string | null;
}

interface EPDData {
  schema: string;
  as_of_date: string;
  n_names: number;
  n_full: number;
  n_partial: number;
  n_event_loaded: number;
  n_skew_extreme: number;
  names: EPDName[];
  error?: string;
}

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || isNaN(v)) return '\u2014';
  return v.toFixed(decimals);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || isNaN(v)) return '\u2014';
  return (v * 100).toFixed(1) + '%';
}

function regimeColor(regime: string): string {
  if (regime.includes('event_loaded')) return 'text-orange-600 font-semibold';
  if (regime.includes('iv_ramping')) return 'text-amber-600';
  if (regime.includes('skew_extreme')) return 'text-rose-600';
  if (regime.includes('iv_crushing')) return 'text-blue-600';
  return 'text-slate-400';
}

function qualityBadge(q: string): string {
  if (q === 'full') return 'bg-emerald-100 text-emerald-700';
  if (q === 'partial') return 'bg-amber-100 text-amber-700';
  return 'bg-slate-100 text-slate-500';
}

export default function EventPremiumPanel({ date, onSelectTicker }: { date: string; onSelectTicker?: (t: string) => void }) {
  const [data, setData] = useState<EPDData | null>(null);
  const [qc, setQc] = useState<any>(null);
  const [sortKey, setSortKey] = useState<string>('epd_event_premium_ratio');
  const [sortDesc, setSortDesc] = useState(true);

  useEffect(() => {
    if (!date) return;
    fetchEventPremiumDecomp(date).then(setData);
    fetchOptionsQCSummary(date).then(d => setQc(d?.error ? null : d));
  }, [date]);

  if (!data || data.error) {
    return <div className="p-6 text-slate-400">No event premium data for {date}</div>;
  }

  const sorted = [...data.names].sort((a, b) => {
    const av = (a as any)[sortKey] ?? -Infinity;
    const bv = (b as any)[sortKey] ?? -Infinity;
    return sortDesc ? bv - av : av - bv;
  });

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDesc(!sortDesc);
    else { setSortKey(key); setSortDesc(true); }
  };

  const arrow = (key: string) => sortKey === key ? (sortDesc ? ' \u25BC' : ' \u25B2') : '';

  const cov = qc?.coverage;
  const sq = qc?.source_quality;
  const noOpt = qc?.no_options_tickers || [];

  return (
    <div className="p-4">
      {/* Source quality strip */}
      {cov && (
        <div className="mb-3 rounded-lg border border-slate-200 bg-white px-4 py-2">
          <div className="flex items-center gap-6 text-[11px]">
            <div>
              <span className="text-slate-400">Coverage</span>{' '}
              <span className="font-semibold text-slate-700">{cov.n_with_options_data}/{cov.n_universe} ({cov.coverage_pct}%)</span>
            </div>
            {sq && Object.entries(sq).map(([src, info]: [string, any]) => (
              <div key={src} className="flex items-center gap-2">
                <span className={`px-1.5 py-0.5 rounded font-semibold ${
                  src === 'tastytrade' ? 'bg-sky-100 text-sky-700' :
                  src === 'polygon' ? 'bg-violet-100 text-violet-700' :
                  'bg-slate-100 text-slate-600'
                }`}>{src}</span>
                <span className="text-slate-600">{info.n_tickers}</span>
                <span className="text-slate-400">iv={info.iv_median ? (info.iv_median * 100).toFixed(0) + '%' : '-'}</span>
                <span className="text-slate-400">ep={(info.event_premium_rate * 100).toFixed(0)}%</span>
                <span className="text-slate-400">judge={info.use_for_judgment_pct.toFixed(0)}%</span>
                {info.n_short_dated > 0 && (
                  <span className="text-amber-600">{info.n_short_dated} short</span>
                )}
              </div>
            ))}
            {noOpt.length > 0 && (
              <div className="text-slate-400">
                No options: {noOpt.length} ({noOpt.slice(0, 5).join(', ')}{noOpt.length > 5 ? '...' : ''})
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-lg font-semibold">Event Premium Decomposition</h2>
          <p className="text-xs text-slate-500">
            {data.n_names} names | {data.n_full} full | {data.n_event_loaded} event-loaded | {data.n_skew_extreme} skew-extreme
          </p>
        </div>
        <span className="text-xs text-slate-400">{data.as_of_date}</span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 sticky top-0">
            <tr>
              <th className="text-left px-2 py-1.5 font-medium">Ticker</th>
              <th className="text-right px-2 py-1.5 font-medium cursor-pointer select-none" onClick={() => toggleSort('epd_event_premium_ratio')}>
                EPR{arrow('epd_event_premium_ratio')}
              </th>
              <th className="text-right px-2 py-1.5 font-medium cursor-pointer select-none" onClick={() => toggleSort('epd_skew_richness_z')}>
                Skew z{arrow('epd_skew_richness_z')}
              </th>
              <th className="text-right px-2 py-1.5 font-medium cursor-pointer select-none" onClick={() => toggleSort('epd_iv_momentum')}>
                IV Mom{arrow('epd_iv_momentum')}
              </th>
              <th className="text-right px-2 py-1.5 font-medium cursor-pointer select-none" onClick={() => toggleSort('epd_iv_per_catalyst_day')}>
                IV/Day{arrow('epd_iv_per_catalyst_day')}
              </th>
              <th className="text-center px-2 py-1.5 font-medium">Prox</th>
              <th className="text-left px-2 py-1.5 font-medium">Regime</th>
              <th className="text-right px-2 py-1.5 font-medium cursor-pointer select-none" onClick={() => toggleSort('epd_event_premium_ratio_z')}>
                EPR z{arrow('epd_event_premium_ratio_z')}
              </th>
              <th className="text-right px-2 py-1.5 font-medium cursor-pointer select-none" onClick={() => toggleSort('epd_iv_momentum_z')}>
                Mom z{arrow('epd_iv_momentum_z')}
              </th>
              <th className="text-center px-2 py-1.5 font-medium">Misprice</th>
              <th className="text-center px-2 py-1.5 font-medium">Qual</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sorted.map((n) => (
              <tr
                key={n.ticker}
                className="hover:bg-slate-50 cursor-pointer"
                onClick={() => onSelectTicker?.(n.ticker)}
              >
                <td className="px-2 py-1 font-mono font-semibold">{n.ticker}</td>
                <td className="px-2 py-1 text-right font-mono">{fmt(n.epd_event_premium_ratio, 3)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmt(n.epd_skew_richness_z)}</td>
                <td className={`px-2 py-1 text-right font-mono ${n.epd_iv_ramping ? 'text-amber-600 font-semibold' : n.epd_iv_crushing ? 'text-blue-600' : ''}`}>
                  {fmtPct(n.epd_iv_momentum)}
                </td>
                <td className="px-2 py-1 text-right font-mono">{fmt(n.epd_iv_per_catalyst_day, 4)}</td>
                <td className="px-2 py-1 text-center">
                  <span className={`inline-block px-1 py-0.5 rounded text-[10px] ${
                    n.epd_catalyst_proximity_bucket === 'imminent' ? 'bg-rose-100 text-rose-700' :
                    n.epd_catalyst_proximity_bucket === 'near' ? 'bg-amber-100 text-amber-700' :
                    n.epd_catalyst_proximity_bucket === 'mid' ? 'bg-slate-100 text-slate-600' :
                    'bg-slate-50 text-slate-400'
                  }`}>
                    {n.epd_catalyst_proximity_bucket || '\u2014'}
                  </span>
                </td>
                <td className={`px-2 py-1 ${regimeColor(n.epd_surface_regime || 'flat')}`}>
                  {n.epd_surface_regime || 'flat'}
                </td>
                <td className="px-2 py-1 text-right font-mono">{fmt(n.epd_event_premium_ratio_z)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmt(n.epd_iv_momentum_z)}</td>
                <td className="px-2 py-1 text-center">
                  {n.epd_mispricing_direction ? (
                    <span className={`text-[10px] font-semibold ${
                      n.epd_mispricing_direction === 'overpriced' ? 'text-rose-600' : 'text-emerald-600'
                    }`}>
                      {n.epd_mispricing_direction === 'overpriced' ? 'OVER' : 'UNDER'}
                    </span>
                  ) : '\u2014'}
                </td>
                <td className="px-2 py-1 text-center">
                  <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${qualityBadge(n.epd_quality)}`}>
                    {n.epd_quality}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
