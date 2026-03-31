import { useEffect, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, ReferenceLine } from 'recharts';
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

function num(v: any): number { const n = parseFloat(v); return isNaN(n) ? 0 : n; }
function pct(v: any): string { const n = parseFloat(v); return isNaN(n) ? '—' : `${(n * 100).toFixed(1)}%`; }
function pctRaw(v: any): string { const n = parseFloat(v); return isNaN(n) ? '—' : `${n.toFixed(1)}%`; }
function val(v: any): string { const n = parseFloat(v); return isNaN(n) ? '—' : n.toFixed(3); }

function Stat({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</div>
      <div className="mt-1 text-lg font-semibold" style={accent ? { color: accent } : {}}>{value}</div>
      {sub && <div className="text-[10px] text-slate-400 mt-0.5">{sub}</div>}
    </div>
  );
}

function ZBar({ val: v, max = 2 }: { val: number; max?: number }) {
  const pctPos = Math.min(1, Math.max(0, (v + max) / (2 * max)));
  const mid = 0.5;
  const barStart = v >= 0 ? mid : pctPos;
  const barWidth = Math.abs(pctPos - mid);
  return (
    <svg width={60} height={14}>
      <rect x={0} y={2} width={60} height={10} rx={3} fill="#f1f5f9" />
      <line x1={30} y1={1} x2={30} y2={13} stroke="#cbd5e1" strokeWidth={1} />
      <rect x={barStart * 60} y={3} width={barWidth * 60} height={8} rx={2} fill={v >= 0 ? '#14b8a6' : '#f97316'} />
    </svg>
  );
}

export default function TickerDetail({ ticker, date }: Props) {
  const [data, setData] = useState<any>(null);
  const [tab, setTab] = useState<'overview' | 'options' | 'portfolio' | 'crt'>('overview');

  useEffect(() => {
    if (ticker && date) {
      fetchTickerDetail(ticker, date).then(setData);
      setTab('overview');
    }
  }, [ticker, date]);

  if (!data || !data.ranking?.ticker) {
    return <div className="p-8 text-slate-400 text-center">Select a ticker</div>;
  }

  const r = data.ranking;
  const pos = data.position || {};
  const opts = data.options || {};
  const crt = data.crt_resolutions || [];

  // Score waterfall — sort contributions from DEM
  const contribs = [
    { name: 'clinical', val: num(r.de_sort_contrib_clinical), fill: '#14b8a6' },
    { name: 'catalyst_bonus', val: num(r.de_sort_contrib_catalyst_bonus), fill: '#f97316' },
    { name: 'cal_alpha', val: num(r.de_sort_contrib_calendar_alpha), fill: '#3b82f6' },
    { name: 'institutional', val: num(r.de_sort_contrib_institutional), fill: '#a855f7' },
    { name: 'coinvest', val: num(r.de_sort_contrib_coinvest), fill: '#6366f1' },
    { name: 'clinical_quality', val: num(r.de_sort_contrib_clinical_quality_91_180), fill: '#0d9488' },
    { name: 'binary_quality', val: num(r.de_sort_contrib_binary_quality), fill: '#eab308' },
  ].filter(d => Math.abs(d.val) > 0.0001);

  const totalSort = num(r.de_sort_total_adj);

  // Options IV term structure
  const termData = [
    { name: 'Front IV', value: num(r.opt_front_iv) * 100 },
    { name: 'ATM IV', value: num(r.opt_atm_iv) * 100 },
    { name: 'Back IV', value: num(r.opt_back_iv) * 100 },
  ].filter(d => d.value > 0);

  const crtBars = crt.map((c: any, i: number) => ({
    name: c.ticker + '-' + (i + 1),
    value: c.outcome === 'HIT' ? 1 : c.outcome === 'MISS' ? -1 : 0,
    fill: c.outcome === 'HIT' ? '#059669' : c.outcome === 'MISS' ? '#e11d48' : '#7c3aed',
  }));

  const catDays = num(r.catalyst_days);
  const isHard = r.is_hard_catalyst === '1';

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* Header */}
      <div className="p-4 border-b bg-white sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold">{ticker}</h2>
          <span className={`text-xs px-2 py-0.5 rounded ${tierColor[r.tier_any] || 'bg-slate-100 text-slate-500'}`}>
            Tier {r.tier_any}
          </span>
          <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600">#{r.actionable_rank}</span>
          {isHard && <span className="text-xs px-2 py-0.5 rounded bg-rose-50 text-rose-700">Hard catalyst</span>}
          {r.opt_iv_regime === 'EXTREME' && <span className="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700">IV Extreme</span>}
        </div>
        <p className="mt-1 text-sm text-slate-500">{r.tier_reason || r.archetype} — {r.catalyst_family} {catDays}d</p>
      </div>

      {/* Key stats row */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-2 p-3">
        <Stat label="optionality" value={pct(r.clinical_optionality_pct_dev)} accent="#0f766e" />
        <Stat label="catalyst_days" value={`${r.catalyst_days || '—'}d`} accent={catDays <= 7 ? '#ef4444' : catDays <= 30 ? '#f59e0b' : undefined} />
        <Stat label="momentum" value={r.mom_state || '—'} />
        <Stat label="ATM IV" value={pctRaw(num(r.opt_atm_iv) * 100)} />
        <Stat label="RR 25d" value={val(r.opt_rr_25d)} accent={num(r.opt_rr_25d) > 0.03 ? '#22c55e' : num(r.opt_rr_25d) < -0.05 ? '#ef4444' : undefined} />
        <Stat label="sort total" value={totalSort.toFixed(3)} />
      </div>

      {/* Tabs */}
      <div className="flex border-b bg-white sticky top-[89px] z-10">
        {(['overview', 'options', 'portfolio', 'crt'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-2 text-sm font-medium capitalize transition ${tab === t ? 'border-b-2 border-emerald-600 text-emerald-700' : 'text-slate-500 hover:text-slate-700'}`}>
            {t === 'crt' ? 'CRT' : t}
          </button>
        ))}
      </div>

      <div className="flex-1 p-4 space-y-4">
        {/* OVERVIEW */}
        {tab === 'overview' && (
          <>
            {/* Score waterfall */}
            {contribs.length > 0 && (
              <div className="rounded-xl border p-3">
                <div className="text-sm font-medium mb-1">Sort contribution decomposition</div>
                <div className="text-xs text-slate-400 mb-2">de_sort_total_adj = {totalSort.toFixed(4)}</div>
                <div className="h-44">
                  <ResponsiveContainer>
                    <BarChart data={contribs} layout="vertical" margin={{ left: 90, right: 16, top: 4, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis type="number" tick={{ fontSize: 10 }} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={85} />
                      <Tooltip formatter={(v: any) => [v.toFixed(4), 'contribution']} />
                      <ReferenceLine x={0} stroke="#94a3b8" />
                      <Bar dataKey="val" radius={[0, 4, 4, 0]}>
                        {contribs.map((d, i) => <Cell key={i} fill={d.fill} fillOpacity={0.8} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Additional context */}
            <div className="grid grid-cols-2 gap-3">
              <Stat label="archetype" value={r.archetype || '—'} />
              <Stat label="clinical_lead_phase" value={r.clinical_lead_phase || r.lead_program_phase || '—'} />
              <Stat label="catalyst_source" value={r.catalyst_source || '—'} />
              <Stat label="catalyst_event_type" value={r.catalyst_event_type || '—'} />
            </div>

            <div className="rounded-xl bg-slate-50 p-3 text-sm">
              <span className="font-medium">Why ranked here: </span>
              {r.tier_reason || `${r.archetype} — ${r.catalyst_family} catalyst in ${r.catalyst_days}d`}
            </div>
          </>
        )}

        {/* OPTIONS */}
        {tab === 'options' && (
          <>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="opt_atm_iv" value={pctRaw(num(r.opt_atm_iv) * 100)} />
              <Stat label="opt_front_iv" value={pctRaw(num(r.opt_front_iv) * 100)} />
              <Stat label="opt_back_iv" value={pctRaw(num(r.opt_back_iv) * 100)} />
              <Stat label="opt_rr_25d" value={val(r.opt_rr_25d)} accent={num(r.opt_rr_25d) > 0.03 ? '#22c55e' : num(r.opt_rr_25d) < -0.05 ? '#ef4444' : undefined} />
              <Stat label="opt_term_slope" value={val(r.opt_term_slope)} />
              <Stat label="opt_put_call_skew" value={val(r.opt_put_call_skew)} />
              <Stat label="opt_event_premium" value={r.opt_event_premium || '—'} accent={r.opt_event_premium === 'YES' ? '#f97316' : undefined} />
              <Stat label="implied_event_move" value={pctRaw(num(r.implied_event_move) * 100)} />
              <Stat label="iv_regime" value={r.opt_iv_regime || '—'} accent={r.opt_iv_regime === 'EXTREME' ? '#ef4444' : undefined} />
              <Stat label="opt_dte" value={r.opt_dte ? `${r.opt_dte}d` : '—'} />
              <Stat label="iv_crush_breakeven" value={pctRaw(num(r.iv_crush_breakeven_pct) * 100)} />
              <Stat label="crush_adj_implied" value={pctRaw(num(r.crush_adjusted_implied_move) * 100)} />
            </div>

            {/* IV term structure chart */}
            {termData.length > 0 && (
              <div className="rounded-xl border p-3">
                <div className="text-sm font-medium mb-1">IV term structure</div>
                <div className="text-xs text-slate-400 mb-2">Front → ATM → Back</div>
                <div className="h-36">
                  <ResponsiveContainer>
                    <BarChart data={termData} margin={{ left: 10, right: 10, top: 4, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v.toFixed(0)}%`} />
                      <Tooltip formatter={(v: any) => [`${v.toFixed(1)}%`, 'IV']} />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                        <Cell fill="#0f766e" />
                        <Cell fill="#3b82f6" />
                        <Cell fill="#7c3aed" />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Options verdict */}
            <div className="rounded-xl bg-slate-50 p-3 text-sm space-y-2">
              <div>
                <span className="font-medium">Diagnostic basis: </span>{r.opt_diagnostic_basis || '—'}
              </div>
              <div>
                <span className="font-medium">Use for judgment: </span>
                <span className={r.opt_use_for_judgment === 'YES' ? 'text-emerald-600 font-semibold' : 'text-slate-500'}>
                  {r.opt_use_for_judgment || '—'}
                </span>
              </div>
              <div>
                <span className="font-medium">Liquidity: </span>
                <span className={r.opt_liquidity_ok === '1' ? 'text-emerald-600' : 'text-rose-600'}>
                  {r.opt_liquidity_ok === '1' ? 'OK' : 'Poor'}
                </span>
              </div>
              {r.opt_iv_regime === 'EXTREME' && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-amber-800">
                  IV regime is EXTREME — review event premium and skew before sizing.
                </div>
              )}
            </div>
          </>
        )}

        {/* PORTFOLIO */}
        {tab === 'portfolio' && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="bucket" value={pos.bucket || '—'} />
              <Stat label="weight_pct" value={pos.weight_pct ? `${pos.weight_pct}%` : '—'} />
              <Stat label="family" value={pos.effective_family || pos.catalyst_family || '—'} />
              <Stat label="regulatory_days" value={pos.regulatory_days ?? '—'} />
              <Stat label="gap_risk" value={pos.gap_risk || '—'} />
              <Stat label="reg_sub_bucket" value={pos.reg_sub_bucket || '—'} />
            </div>
            {!pos.bucket && (
              <div className="rounded-xl border border-dashed p-4 text-sm text-slate-400 text-center">
                Not in shadow portfolio
              </div>
            )}
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
                {crtBars.length > 0 && (
                  <div className="h-32">
                    <ResponsiveContainer>
                      <BarChart data={crtBars} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                        <YAxis tick={{ fontSize: 10 }} domain={[-1, 1]} />
                        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                          {crtBars.map((b: any, i: number) => <Cell key={i} fill={b.fill} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
                <div className="space-y-2">
                  {crt.map((c: any, i: number) => (
                    <div key={i} className={`flex justify-between items-center rounded-xl p-3 ${outcomeColor[c.outcome] || 'bg-slate-50'}`}>
                      <div>
                        <div className="font-semibold">{c.outcome}</div>
                        <div className="text-xs opacity-70">rank: {c.prediction_dem_rank ?? 'unranked'} · {c.catalyst_date}</div>
                      </div>
                      <div className="text-sm font-medium">{c.price_direction || '—'}</div>
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
