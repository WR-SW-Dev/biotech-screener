import { useEffect, useState } from 'react';
// Icons available if needed: Activity, TrendingUp, Shield, Sparkles
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell } from 'recharts';
import { fetchTickerDetail } from './api';

interface Props {
  ticker: string;
  date: string;
}

const tierColor: Record<string, string> = {
  A: 'bg-emerald-100 text-emerald-800',
  B: 'bg-amber-100 text-amber-800',
  C: 'bg-slate-100 text-slate-700',
};

const outcomeColor: Record<string, string> = {
  HIT: 'text-emerald-600 bg-emerald-50',
  MISS: 'text-rose-600 bg-rose-50',
  EXOGENOUS: 'text-violet-600 bg-violet-50',
  NEEDS_REVIEW: 'text-slate-500 bg-slate-50',
};

function num(v: any): number {
  const n = parseFloat(v);
  return isNaN(n) ? 0 : n;
}

function pct(v: any): string {
  const n = parseFloat(v);
  return isNaN(n) ? '—' : `${n.toFixed(1)}%`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3">
      <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

export default function TickerDetail({ ticker, date }: Props) {
  const [data, setData] = useState<any>(null);
  const [tab, setTab] = useState<'overview' | 'options' | 'portfolio' | 'crt'>('overview');

  useEffect(() => {
    if (ticker && date) {
      fetchTickerDetail(ticker, date).then(setData);
    }
  }, [ticker, date]);

  if (!data || !data.ranking?.ticker) {
    return <div className="p-8 text-slate-400 text-center">Select a ticker from the rankings table</div>;
  }

  const r = data.ranking;
  const pos = data.position || {};
  const opts = data.options || {};
  const crt = data.crt_resolutions || [];

  const scoreData = [
    { name: 'optionality', value: num(r.clinical_optionality_pct_dev) * 100, color: '#0f766e' },
    { name: 'alpha_cohort', value: num(r.alpha_cohort_pct) * 100, color: '#2563eb' },
    { name: 'implied_move', value: num(opts.actual_implied_move_pctile), color: '#7c3aed' },
  ];

  const crtBars = crt.map((c: any, i: number) => ({
    name: `${c.outcome}-${i + 1}`,
    value: c.outcome === 'HIT' ? 1 : c.outcome === 'MISS' ? -1 : 0,
    fill: c.outcome === 'HIT' ? '#059669' : c.outcome === 'MISS' ? '#e11d48' : '#7c3aed',
  }));

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* Header */}
      <div className="p-4 border-b bg-white sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold">{ticker}</h2>
          <span className={`text-xs px-2 py-0.5 rounded ${tierColor[r.tier_any] || 'bg-slate-100 text-slate-500'}`}>
            Tier {r.tier_any}
          </span>
          <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600">
            Rank #{r.actionable_rank}
          </span>
        </div>
        <p className="mt-1 text-sm text-slate-500">{r.tier_reason || r.archetype}</p>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 p-4">
        <Stat label="catalyst_days" value={r.catalyst_days || '—'} />
        <Stat label="family" value={r.catalyst_family || '—'} />
        <Stat label="hard" value={r.is_hard_catalyst === '1' ? 'Yes' : 'No'} />
        <Stat label="mom_state" value={r.mom_state || '—'} />
      </div>

      {/* Tabs */}
      <div className="flex border-b bg-white sticky top-[73px] z-10">
        {(['overview', 'options', 'portfolio', 'crt'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2.5 text-sm font-medium capitalize transition ${
              tab === t ? 'border-b-2 border-emerald-600 text-emerald-700' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {t === 'crt' ? 'CRT' : t}
          </button>
        ))}
      </div>

      <div className="flex-1 p-4 space-y-4">
        {/* Overview */}
        {tab === 'overview' && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Stat label="clinical_optionality_pct_dev" value={pct(num(r.clinical_optionality_pct_dev) * 100)} />
              <Stat label="alpha_cohort_pct" value={pct(num(r.alpha_cohort_pct) * 100)} />
            </div>
            <div className="rounded-xl border p-3">
              <div className="text-sm font-medium mb-2">Score context</div>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={scoreData} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip formatter={(v: any) => [`${v.toFixed(1)}`, 'value']} />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                      {scoreData.map((d, i) => <Cell key={i} fill={d.color} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3 text-sm">
              <span className="font-medium">Why ranked here: </span>
              {r.tier_reason || `${r.archetype} with ${r.catalyst_family} catalyst in ${r.catalyst_days} days`}
            </div>
          </>
        )}

        {/* Options */}
        {tab === 'options' && (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Stat label="atm_iv_change_5d" value={pct(opts.atm_iv_change_5d)} />
              <Stat label="opt_rr_25d" value={num(opts.opt_rr_25d).toFixed(3)} />
              <Stat label="implied_move_pctile" value={pct(opts.actual_implied_move_pctile)} />
            </div>
            <div className="rounded-xl bg-slate-50 p-3 text-sm">
              {num(opts.actual_implied_move_pctile) >= 90
                ? 'Elevated options regime — review event premium and skew before changing exposure.'
                : 'No extreme options setup from current diagnostics.'}
            </div>
          </>
        )}

        {/* Portfolio */}
        {tab === 'portfolio' && (
          <div className="space-y-3">
            <Stat label="bucket" value={pos.bucket || '—'} />
            <Stat label="weight_pct" value={pos.weight_pct ? `${pos.weight_pct}%` : '—'} />
            <Stat label="family" value={pos.family || pos.catalyst_family || '—'} />
            <Stat label="regulatory_days" value={pos.regulatory_days ?? '—'} />
          </div>
        )}

        {/* CRT */}
        {tab === 'crt' && (
          <>
            {crt.length === 0 ? (
              <div className="rounded-xl border border-dashed p-6 text-sm text-slate-400 text-center">
                No CRT resolution history for {ticker}
              </div>
            ) : (
              <>
                <div className="h-40">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={crtBars} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} domain={[-1, 1]} />
                      <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                        {crtBars.map((b: any, i: number) => <Cell key={i} fill={b.fill} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-2">
                  {crt.map((c: any, i: number) => (
                    <div key={i} className={`flex justify-between items-center rounded-xl p-3 ${outcomeColor[c.outcome] || 'bg-slate-50'}`}>
                      <div>
                        <div className="font-semibold">{c.outcome}</div>
                        <div className="text-xs opacity-70">rank: {c.prediction_dem_rank ?? 'unranked'}</div>
                      </div>
                      <div className="text-sm">{c.price_direction || '—'}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
