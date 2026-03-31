import { useEffect, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, ReferenceLine } from 'recharts';
import { fetchCRTResolutions } from './api';

const GREEN = '#22c55e';
const RED = '#ef4444';
const AMBER = '#f59e0b';

function Stat({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3">
      <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
      <div className="mt-1 text-xl font-semibold" style={{ color }}>{value}</div>
    </div>
  );
}

export default function CRTCalibration() {
  const [records, setRecords] = useState<any[]>([]);

  useEffect(() => {
    fetchCRTResolutions().then((r) => setRecords(r.filter((d: any) => d.outcome === 'HIT' || d.outcome === 'MISS')));
  }, []);

  const buckets = [
    { label: 'Top 10', lo: 1, hi: 10 },
    { label: '11-25', lo: 11, hi: 25 },
    { label: '26-50', lo: 26, hi: 50 },
    { label: '51-100', lo: 51, hi: 100 },
    { label: 'Unranked', lo: 101, hi: 9999 },
  ];

  const hitByBucket = buckets.map((b) => {
    const inB = records.filter((d) => {
      const rank = d.prediction_dem_rank ?? 9999;
      return rank >= b.lo && rank <= b.hi;
    });
    const hits = inB.filter((d) => d.outcome === 'HIT').length;
    return { bucket: b.label, n: inB.length, hits, rate: inB.length ? hits / inB.length : 0 };
  });

  const returnByBucket = buckets.map((b) => {
    const inB = records.filter((d) => {
      const rank = d.prediction_dem_rank ?? 9999;
      return rank >= b.lo && rank <= b.hi;
    });
    if (!inB.length) return { bucket: b.label, avgReturn: 0, n: 0 };
    const prices = inB.filter((d) => d.price_t_minus_1 && d.price_t_0);
    if (!prices.length) return { bucket: b.label, avgReturn: 0, n: inB.length };
    const avg = prices.reduce((s, d) => s + (d.price_t_0 - d.price_t_minus_1) / d.price_t_minus_1, 0) / prices.length;
    return { bucket: b.label, avgReturn: +(avg * 100).toFixed(1), n: inB.length };
  });

  const totalHits = records.filter((d) => d.outcome === 'HIT').length;
  const totalMisses = records.filter((d) => d.outcome === 'MISS').length;

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <h2 className="text-xl font-semibold">CRT Calibration</h2>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat label="Resolutions" value={records.length} />
        <Stat label="HITs" value={totalHits} color={GREEN} />
        <Stat label="MISSes" value={totalMisses} color={RED} />
        <Stat label="Hit rate (ranked)" value={`${records.length ? ((totalHits / records.length) * 100).toFixed(0) : 0}%`} />
        <Stat label="RR status" value="1/3" color={AMBER} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-xl border p-4">
          <div className="text-sm font-medium mb-1">Hit rate by DEM rank bucket</div>
          <div className="text-xs text-slate-400 mb-3">Does rank predict outcomes?</div>
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={hitByBucket}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                <Tooltip formatter={(v: any) => [`${(v * 100).toFixed(0)}%`, 'Hit rate']} />
                <Bar dataKey="rate" radius={[4, 4, 0, 0]}>
                  {hitByBucket.map((d, i) => (
                    <Cell key={i} fill={d.rate >= 0.5 ? GREEN : d.rate > 0 ? AMBER : RED} fillOpacity={0.7} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-xl border p-4">
          <div className="text-sm font-medium mb-1">Avg return by rank bucket</div>
          <div className="text-xs text-slate-400 mb-3">Does rank predict magnitude?</div>
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={returnByBucket}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
                <Tooltip formatter={(v: any) => [`${v}%`, 'Avg return']} />
                <ReferenceLine y={0} stroke="#94a3b8" />
                <Bar dataKey="avgReturn" radius={[4, 4, 0, 0]}>
                  {returnByBucket.map((d, i) => (
                    <Cell key={i} fill={d.avgReturn >= 0 ? GREEN : RED} fillOpacity={0.7} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Resolution table */}
      <div className="rounded-xl border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              {['Ticker', 'Outcome', 'Rank', 'Price Dir', 'Return', 'Flag'].map((h) => (
                <th key={h} className="text-left px-3 py-2 text-xs font-medium text-slate-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {records.map((d, i) => {
              const ret = d.price_t_minus_1 && d.price_t_0
                ? ((d.price_t_0 - d.price_t_minus_1) / d.price_t_minus_1 * 100).toFixed(1)
                : '—';
              const flag = d.ticker === 'AQST' ? 'CRL + positive price'
                : d.ticker === 'MAZE' ? 'Rank 36 MISS'
                : null;
              return (
                <tr key={i} className="border-t hover:bg-slate-50">
                  <td className="px-3 py-2 font-semibold text-indigo-600">{d.ticker}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded ${d.outcome === 'HIT' ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}`}>
                      {d.outcome}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{d.prediction_dem_rank ? `#${d.prediction_dem_rank}` : '—'}</td>
                  <td className="px-3 py-2 text-xs">{d.price_direction || '—'}</td>
                  <td className="px-3 py-2 font-mono text-xs" style={{ color: parseFloat(ret) >= 0 ? GREEN : RED }}>
                    {ret !== '—' ? `${parseFloat(ret) >= 0 ? '+' : ''}${ret}%` : '—'}
                  </td>
                  <td className="px-3 py-2">
                    {flag && <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800">{flag}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
