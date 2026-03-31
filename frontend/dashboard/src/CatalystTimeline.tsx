import { useMemo } from 'react';
import { ResponsiveContainer, ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Cell, ZAxis } from 'recharts';

interface Props {
  rows: any[];
  onSelectTicker: (ticker: string) => void;
}

const tierColor: Record<string, string> = {
  A: 'bg-emerald-100 text-emerald-800',
  B: 'bg-amber-100 text-amber-800',
  C: 'bg-slate-100 text-slate-700',
};

function num(v: any): number { const n = parseFloat(v); return isNaN(n) ? 0 : n; }

export default function CatalystTimeline({ rows, onSelectTicker }: Props) {
  // Filter to names with catalyst_days <= 120
  const events = useMemo(() => {
    return rows
      .filter((r) => {
        const d = num(r.catalyst_days);
        return d > 0 && d <= 120;
      })
      .sort((a, b) => num(a.catalyst_days) - num(b.catalyst_days));
  }, [rows]);

  const scatterData = events.map((r) => ({
    ticker: r.ticker,
    catalyst_days: num(r.catalyst_days),
    opt_rr_25d: num(r.opt_rr_25d) * 100,
    composite: num(r.composite_score) || 50,
    tier: r.tier_any,
    is_hard: r.is_hard_catalyst === '1',
    catalyst_type: r.catalyst_event_type || '—',
    catalyst_family: r.catalyst_family || '—',
  }));

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <h2 className="text-xl font-semibold">Catalyst Timeline</h2>

      {/* Scatter: RR vs catalyst proximity */}
      <div className="rounded-xl border p-4">
        <div className="text-sm font-medium mb-1">RR 25d vs catalyst proximity</div>
        <div className="text-xs text-slate-400 mb-3">Bubble size = composite score. Green = A-tier, Amber = B-tier, Gray = C/D.</div>
        <div className="h-64">
          <ResponsiveContainer>
            <ScatterChart margin={{ left: 10, right: 20, top: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="catalyst_days" name="Days" tick={{ fontSize: 10 }} label={{ value: 'Days to catalyst', fontSize: 10, position: 'bottom', offset: -5 }} />
              <YAxis dataKey="opt_rr_25d" name="RR 25d %" tick={{ fontSize: 10 }} label={{ value: 'RR 25d (%)', fontSize: 10, angle: -90, position: 'left' }} />
              <ZAxis dataKey="composite" range={[30, 150]} />
              <Tooltip content={({ active, payload }) => {
                if (!active || !payload?.[0]) return null;
                const d = payload[0].payload;
                return (
                  <div className="bg-white border rounded-lg shadow-sm px-3 py-2 text-xs">
                    <div className="font-semibold text-indigo-600">{d.ticker}</div>
                    <div>{d.catalyst_type} · {d.catalyst_family}</div>
                    <div>RR: {d.opt_rr_25d.toFixed(1)}% · {d.catalyst_days}d</div>
                    <div>Tier {d.tier} · {d.is_hard ? 'Hard' : 'Soft'}</div>
                  </div>
                );
              }} />
              <Scatter data={scatterData} onClick={(d: any) => onSelectTicker(d.ticker)}>
                {scatterData.map((d, i) => (
                  <Cell
                    key={i}
                    fill={d.tier === 'A' ? '#0f766e' : d.tier === 'B' ? '#b45309' : '#64748b'}
                    fillOpacity={d.is_hard ? 0.9 : 0.4}
                    stroke={d.is_hard ? '#ef4444' : 'none'}
                    strokeWidth={d.is_hard ? 1.5 : 0}
                  />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
        <div className="flex gap-4 text-[10px] text-slate-400 mt-2">
          <span><span className="text-red-500">○</span> Red ring = hard catalyst</span>
          <span>Opacity: hard = solid, soft = faded</span>
          <span>Click to select ticker</span>
        </div>
      </div>

      {/* Event list */}
      <div className="rounded-xl border overflow-hidden">
        <div className="bg-slate-50 px-4 py-2 text-sm font-medium">
          Upcoming catalysts — {events.length} events in 120d
        </div>
        <div className="divide-y max-h-[400px] overflow-auto">
          {events.slice(0, 30).map((r, i) => {
            const days = num(r.catalyst_days);
            const rr = num(r.opt_rr_25d);
            return (
              <button
                key={i}
                onClick={() => onSelectTicker(r.ticker)}
                className="w-full grid grid-cols-[3rem_4rem_8rem_1fr_5rem_3rem] gap-2 px-4 py-2.5 text-left text-sm hover:bg-slate-50 transition"
              >
                <span className={`font-semibold ${days <= 7 ? 'text-red-500' : days <= 30 ? 'text-amber-600' : 'text-slate-500'}`}>
                  {days}d
                </span>
                <span className="font-semibold text-indigo-600">{r.ticker}</span>
                <span className="text-slate-500 truncate">{r.company_name || r.ticker}</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">{r.catalyst_event_type || '—'}</span>
                  {r.is_hard_catalyst === '1' && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-50 text-rose-700">Hard</span>
                  )}
                </div>
                <span className={`text-right font-mono text-xs ${rr > 0.03 ? 'text-emerald-600' : rr < -0.05 ? 'text-rose-600' : 'text-slate-500'}`}>
                  RR {rr > 0 ? '+' : ''}{(rr * 100).toFixed(1)}
                </span>
                <span className={`text-right text-xs px-1.5 py-0.5 rounded ${tierColor[r.tier_any] || 'bg-slate-100 text-slate-500'}`}>
                  #{r.actionable_rank}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
