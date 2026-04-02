import { useEffect, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, ReferenceLine } from 'recharts';
import { fetchTickerDetail, fetchDealComps, fetchPurpleBook, fetchAACTTrials } from './api';

interface Props { ticker: string; date: string; }

const tierBg: Record<string, string> = { A: 'bg-emerald-100 text-emerald-800', B: 'bg-amber-100 text-amber-800', C: 'bg-slate-100 text-slate-700' };
const outcomeBg: Record<string, string> = { HIT: 'bg-emerald-50 text-emerald-700', MISS: 'bg-rose-50 text-rose-700', EXOGENOUS: 'bg-violet-50 text-violet-700' };

function n(v: any): number { const x = parseFloat(v); return isNaN(x) ? 0 : x; }
function fmt(v: any, suf = ''): string { const x = parseFloat(v); return isNaN(x) ? '—' : x.toFixed(2) + suf; }
function fmtPct(v: any): string { const x = parseFloat(v); return isNaN(x) ? '—' : (x * 100).toFixed(1) + '%'; }
function fmtRaw(v: any): string { return v === '' || v === undefined || v === null ? '—' : String(v); }

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="text-[10px] text-slate-400 uppercase tracking-wide truncate">{label}</div>
      <div className="text-base font-semibold mt-0.5 truncate" style={accent ? { color: accent } : {}}>{value}</div>
    </div>
  );
}

export default function TickerDetail({ ticker, date }: Props) {
  const [data, setData] = useState<any>(null);
  const [dealComps, setDealComps] = useState<any>(null);
  const [purpleBook, setPurpleBook] = useState<any>(null);
  const [aactTrials, setAactTrials] = useState<any>(null);
  const [tab, setTab] = useState<string>('overview');
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!ticker || !date) return;
    setErr('');
    fetchTickerDetail(ticker, date)
      .then(d => { setData(d); setTab('overview'); })
      .catch(e => setErr(String(e)));
    fetchDealComps(ticker, date)
      .then(setDealComps)
      .catch(() => setDealComps(null));
    fetchPurpleBook(ticker, date)
      .then(setPurpleBook)
      .catch(() => setPurpleBook(null));
    fetchAACTTrials(ticker)
      .then(setAactTrials)
      .catch(() => setAactTrials(null));
  }, [ticker, date]);

  if (err) return <div className="p-6 text-rose-500 text-sm">{err}</div>;
  if (!data?.ranking?.ticker) return <div className="p-6 text-slate-400 text-center text-sm">Select a ticker</div>;

  const r = data.ranking;
  const pos = data.position || {};
  const crt: any[] = data.crt_resolutions || [];
  const catDays = n(r.catalyst_days);
  const isHard = r.is_hard_catalyst === '1';

  // Sort contributions — filter out zeros
  const contribs = Object.entries(r)
    .filter(([k, v]) => k.startsWith('de_sort_contrib_') && Math.abs(n(v)) > 0.00001)
    .map(([k, v]) => ({ name: k.replace('de_sort_contrib_', ''), val: n(v) }))
    .sort((a, b) => Math.abs(b.val) - Math.abs(a.val));

  // IV term structure — these are raw IV values (e.g., 2.06 = 206%)
  const termData = [
    { name: 'Front', value: n(r.opt_front_iv) * 100 },
    { name: 'ATM', value: n(r.opt_atm_iv) * 100 },
    { name: 'Back', value: n(r.opt_back_iv) * 100 },
  ].filter(d => d.value > 0);

  const crtBars = crt.map((c: any, i: number) => ({
    name: `${c.outcome}-${i + 1}`,
    value: c.outcome === 'HIT' ? 1 : c.outcome === 'MISS' ? -1 : 0,
    fill: c.outcome === 'HIT' ? '#059669' : c.outcome === 'MISS' ? '#e11d48' : '#7c3aed',
  }));

  return (
    <div className="flex flex-col h-full overflow-auto text-sm">
      {/* Header */}
      <div className="p-3 border-b bg-white sticky top-0 z-10">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xl font-bold">{ticker}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${tierBg[r.tier_any] || 'bg-slate-100'}`}>Tier {r.tier_any}</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100">#{r.actionable_rank}</span>
          {isHard && <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-50 text-rose-700">Hard</span>}
          {r.opt_iv_regime === 'EXTREME' && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-700">IV Extreme</span>}
        </div>
        <div className="text-xs text-slate-500 mt-1">{r.company_name} — {r.archetype} — {r.catalyst_family} {catDays}d</div>
      </div>

      {/* Key stats */}
      <div className="grid grid-cols-3 gap-1.5 p-2">
        <Stat label="optionality" value={fmtPct(r.clinical_optionality_pct_dev)} accent="#0f766e" />
        <Stat label="catalyst" value={`${catDays}d ${isHard ? '🎯' : '○'}`} accent={catDays <= 7 ? '#ef4444' : catDays <= 30 ? '#f59e0b' : undefined} />
        <Stat label="momentum" value={fmtRaw(r.mom_state)} />
        <Stat label="ATM IV" value={fmt(n(r.opt_atm_iv) * 100, '%')} />
        <Stat label="RR 25d" value={fmt(r.opt_rr_25d)} accent={n(r.opt_rr_25d) > 0.03 ? '#22c55e' : n(r.opt_rr_25d) < -0.05 ? '#ef4444' : undefined} />
        <Stat label="tier_reason" value={fmtRaw(r.tier_any_reason)} />
      </div>

      {/* Tabs */}
      <div className="flex border-b bg-white sticky top-[76px] z-10 text-xs">
        {['overview', 'options', 'portfolio', 'trials', 'deals', 'bio', 'crt'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-2 font-medium capitalize text-[11px] ${tab === t ? 'border-b-2 border-emerald-600 text-emerald-700' : 'text-slate-400'}`}>
            {t === 'crt' ? 'CRT' : t}
          </button>
        ))}
      </div>

      <div className="flex-1 p-3 space-y-3">
        {/* OVERVIEW */}
        {tab === 'overview' && <>
          {contribs.length > 0 ? (
            <div className="rounded-lg border p-2">
              <div className="text-xs font-medium mb-1">Sort contributions (de_sort_total = {fmt(r.de_sort_total_adj)})</div>
              <div className="h-36">
                <ResponsiveContainer>
                  <BarChart data={contribs} layout="vertical" margin={{ left: 80, right: 10, top: 2, bottom: 2 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis type="number" tick={{ fontSize: 9 }} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={75} />
                    <Tooltip formatter={(v: any) => [n(v).toFixed(4), 'contrib']} />
                    <ReferenceLine x={0} stroke="#94a3b8" />
                    <Bar dataKey="val" radius={[0, 3, 3, 0]}>
                      {contribs.map((d, i) => <Cell key={i} fill={d.val >= 0 ? '#14b8a6' : '#f97316'} fillOpacity={0.8} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : (
            <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
              Sort contributions are zero — this name is ranked by optionality anchor, not sort-key tiebreaking.
            </div>
          )}
          <div className="grid grid-cols-2 gap-1.5">
            <Stat label="archetype" value={fmtRaw(r.archetype)} />
            <Stat label="phase" value={fmtRaw(r.lead_program_phase)} />
            <Stat label="catalyst_source" value={fmtRaw(r.catalyst_source)} />
            <Stat label="event_type" value={fmtRaw(r.catalyst_event_type)} />
            <Stat label="coinvest" value={fmtRaw(r.coinvest_tag)} />
            <Stat label="runway" value={fmtRaw(r.runway_bucket)} />
          </div>
        </>}

        {/* OPTIONS */}
        {tab === 'options' && <>
          {/* Quality assessment banner */}
          {(() => {
            const liqState = (r.opt_liquidity_state || 'absent') as 'liquid' | 'thin' | 'absent';
            const judgment = r.opt_use_for_judgment === 'YES';
            const featureCount = [r.opt_atm_iv, r.opt_front_iv, r.opt_back_iv, r.opt_term_slope, r.opt_put_call_skew, r.opt_rr_25d, r.opt_event_premium, r.actual_implied_move_pctile, r.implied_event_move].filter(v => v && v.trim()).length;
            const stateColor = liqState === 'liquid' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : liqState === 'thin' ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-slate-50 text-slate-500 border-slate-200';
            const label = liqState === 'liquid' ? 'Liquid chain' : liqState === 'thin' ? 'Thin chain' : 'No options data';
            return (
              <div className={`rounded-lg border px-3 py-2 text-xs flex items-center justify-between ${stateColor}`}>
                <div>
                  <span className="font-semibold">{label}</span>
                  <span className="ml-2 opacity-70">{featureCount}/9 features · {judgment ? 'Use for judgment' : 'Diagnostic only'}</span>
                </div>
                <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white/50">{liqState.toUpperCase()}</span>
              </div>
            );
          })()}
          <div className="grid grid-cols-3 gap-1.5">
            <Stat label="opt_atm_iv" value={fmt(n(r.opt_atm_iv) * 100, '%')} />
            <Stat label="opt_front_iv" value={fmt(n(r.opt_front_iv) * 100, '%')} />
            <Stat label="opt_back_iv" value={fmt(n(r.opt_back_iv) * 100, '%')} />
            <Stat label="opt_rr_25d" value={fmt(r.opt_rr_25d)} accent={n(r.opt_rr_25d) > 0.03 ? '#22c55e' : n(r.opt_rr_25d) < -0.05 ? '#ef4444' : undefined} />
            <Stat label="term_slope" value={fmt(r.opt_term_slope)} />
            <Stat label="put_call_skew" value={fmt(r.opt_put_call_skew)} />
            <Stat label="event_premium" value={fmtRaw(r.opt_event_premium)} accent={r.opt_event_premium === 'YES' ? '#f97316' : undefined} />
            <Stat label="implied_move" value={fmtPct(r.implied_event_move)} />
            <Stat label="iv_regime" value={fmtRaw(r.opt_iv_regime)} accent={r.opt_iv_regime === 'EXTREME' ? '#ef4444' : undefined} />
            <Stat label="opt_dte" value={r.opt_dte ? `${r.opt_dte}d` : '—'} />
            <Stat label="crush_breakeven" value={fmtPct(r.iv_crush_breakeven_pct)} />
            <Stat label="crush_adj_move" value={fmtPct(r.crush_adjusted_implied_move)} />
          </div>
          {termData.length > 0 && (
            <div className="rounded-lg border p-2">
              <div className="text-xs font-medium mb-1">IV term structure</div>
              <div className="h-32">
                <ResponsiveContainer>
                  <BarChart data={termData} margin={{ left: 5, right: 5, top: 2, bottom: 2 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                    <YAxis tick={{ fontSize: 9 }} tickFormatter={v => `${v.toFixed(0)}%`} />
                    <Tooltip formatter={(v: any) => [`${v.toFixed(1)}%`, 'IV']} />
                    <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                      <Cell fill="#0f766e" /><Cell fill="#3b82f6" /><Cell fill="#7c3aed" />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
          <div className="rounded-lg bg-slate-50 p-2 text-xs space-y-1">
            <div><span className="font-medium">Basis:</span> {fmtRaw(r.opt_diagnostic_basis)}</div>
            <div><span className="font-medium">Use for judgment:</span> <span className={r.opt_use_for_judgment === 'YES' ? 'text-emerald-600 font-semibold' : ''}>{fmtRaw(r.opt_use_for_judgment)}</span></div>
            <div><span className="font-medium">Liquidity:</span> <span className={r.opt_liquidity_state === 'liquid' ? 'text-emerald-600' : r.opt_liquidity_state === 'thin' ? 'text-amber-600' : 'text-rose-600'}>{(r.opt_liquidity_state || 'absent').toUpperCase()}</span></div>
          </div>
        </>}

        {/* PORTFOLIO */}
        {tab === 'portfolio' && <>
          {pos.bucket ? (
            <div className="grid grid-cols-2 gap-1.5">
              <Stat label="bucket" value={fmtRaw(pos.bucket)} />
              <Stat label="weight_pct" value={pos.weight_pct ? `${n(pos.weight_pct).toFixed(2)}%` : '—'} />
              <Stat label="family" value={fmtRaw(pos.effective_family)} />
              <Stat label="regulatory_days" value={fmtRaw(pos.regulatory_days)} />
              <Stat label="gap_risk" value={fmtRaw(pos.gap_risk) || 'none'} />
              <Stat label="target_dollars" value={pos.target_dollars ? `$${n(pos.target_dollars).toFixed(0)}` : '—'} />
            </div>
          ) : (
            <div className="rounded-lg border border-dashed p-4 text-slate-400 text-center">Not in shadow portfolio</div>
          )}
        </>}

        {/* TRIALS */}
        {tab === 'trials' && <>
          {!aactTrials || aactTrials.n_trials === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-slate-400 text-center text-xs">
              {aactTrials?.status === 'no_data'
                ? 'No AACT data loaded. Run tools/fetch_aact_snapshot.py first.'
                : `No clinical trials found for ${ticker}`}
            </div>
          ) : <>
            <div className="grid grid-cols-3 gap-1.5">
              <Stat label="total trials" value={String(aactTrials.n_trials)} />
              <Stat label="recruiting" value={String(aactTrials.status_distribution?.['Recruiting'] || 0)} accent="#0f766e" />
              <Stat label="completed" value={String(aactTrials.status_distribution?.['Completed'] || 0)} />
            </div>

            {/* Phase distribution */}
            {aactTrials.phase_distribution && (
              <div className="flex gap-2 flex-wrap text-xs">
                {Object.entries(aactTrials.phase_distribution as Record<string, number>)
                  .filter(([p]) => p && p !== 'Not Applicable' && p !== '')
                  .map(([phase, count]) => (
                    <span key={phase} className={`px-2 py-0.5 rounded ${
                      phase.includes('3') ? 'bg-emerald-50 text-emerald-700' :
                      phase.includes('2') ? 'bg-blue-50 text-blue-700' :
                      'bg-slate-50 text-slate-600'
                    }`}>
                      {phase}: {count}
                    </span>
                  ))}
              </div>
            )}

            {/* Trial list */}
            <div className="rounded-lg border overflow-hidden">
              <div className="bg-slate-50 px-3 py-1.5 text-xs font-medium">
                Trials ({aactTrials.n_trials}) — snapshot {aactTrials.snapshot_date}
              </div>
              <div className="divide-y max-h-[350px] overflow-auto">
                {aactTrials.trials?.map((t: any, i: number) => {
                  const isActive = ['Recruiting', 'Active, not recruiting', 'Enrolling by invitation', 'Not yet recruiting'].includes(t.overall_status);
                  return (
                    <div key={i} className="px-3 py-2 text-xs">
                      <div className="flex justify-between items-start gap-2">
                        <div className="flex-1 min-w-0">
                          <span className="font-mono text-[10px] text-slate-400">{t.nct_id}</span>
                          {t.phase && <span className={`ml-1.5 text-[10px] px-1 rounded ${
                            t.phase.includes('3') ? 'bg-emerald-50 text-emerald-700' :
                            t.phase.includes('2') ? 'bg-blue-50 text-blue-700' :
                            'bg-slate-100 text-slate-600'
                          }`}>{t.phase}</span>}
                          {t.has_results && <span className="ml-1 text-[10px] px-1 rounded bg-violet-50 text-violet-600">results</span>}
                        </div>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap ${
                          isActive ? 'bg-emerald-50 text-emerald-700' :
                          t.overall_status === 'Completed' ? 'bg-blue-50 text-blue-600' :
                          t.overall_status === 'Terminated' ? 'bg-rose-50 text-rose-600' :
                          'bg-slate-50 text-slate-500'
                        }`}>{t.overall_status}</span>
                      </div>
                      <div className="text-slate-600 mt-0.5 line-clamp-2">{t.brief_title}</div>
                      <div className="flex gap-3 mt-0.5 text-[10px] text-slate-400">
                        {t.enrollment && <span>n={t.enrollment}</span>}
                        {t.primary_completion_date && <span>PCD: {t.primary_completion_date}</span>}
                        {t.condition_names?.length > 0 && <span className="truncate">{t.condition_names.join(', ')}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>}
        </>}

        {/* DEALS */}
        {tab === 'deals' && <>
          {!dealComps || dealComps.n_comps === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-slate-400 text-center text-xs">
              {dealComps?.status === 'no_data'
                ? 'No DealForma data loaded. Run scripts/ingest_dealforma.py first.'
                : `No deal comps found for ${ticker} in ${dealComps?.bucket || 'any bucket'}`}
            </div>
          ) : <>
            {/* Summary stats */}
            <div className="grid grid-cols-3 gap-1.5">
              <Stat label="comps found" value={String(dealComps.n_comps)} />
              <Stat label="median upfront" value={dealComps.median_upfront_mm != null ? `$${dealComps.median_upfront_mm}M` : '—'} accent="#0f766e" />
              <Stat label="median total" value={dealComps.median_total_mm != null ? `$${dealComps.median_total_mm}M` : '—'} accent="#3b82f6" />
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs">
              <div><span className="font-medium">Bucket:</span> {dealComps.bucket}</div>
              <div><span className="font-medium">Lookback:</span> {dealComps.lookback_months} months</div>
              {dealComps.cvr_prevalence != null && (
                <div><span className="font-medium">CVR prevalence:</span> {(dealComps.cvr_prevalence * 100).toFixed(1)}%</div>
              )}
            </div>

            {/* Deal type split */}
            {dealComps.deal_type_split && (
              <div className="flex gap-3 text-xs">
                {Object.entries(dealComps.deal_type_split as Record<string, number>).map(([type, count]) => (
                  <span key={type} className="px-2 py-1 rounded bg-slate-100">
                    <span className="font-medium">{type}:</span> {count}
                  </span>
                ))}
              </div>
            )}

            {/* Top acquirers */}
            {dealComps.top_acquirers?.length > 0 && (
              <div className="rounded-lg border p-2">
                <div className="text-xs font-medium mb-1">Top acquirers in bucket</div>
                <div className="space-y-0.5">
                  {dealComps.top_acquirers.map((a: any, i: number) => (
                    <div key={i} className="flex justify-between text-xs">
                      <span className="text-slate-600">{a.name}</span>
                      <span className="font-mono text-slate-400">{a.count} deals</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recent deals table */}
            {dealComps.recent_deals?.length > 0 && (
              <div className="rounded-lg border overflow-hidden">
                <div className="bg-slate-50 px-3 py-1.5 text-xs font-medium">Recent deals</div>
                <div className="divide-y max-h-[250px] overflow-auto">
                  {dealComps.recent_deals.map((d: any, i: number) => (
                    <div key={i} className="px-3 py-1.5 text-xs grid grid-cols-[5rem_1fr_4rem_4rem] gap-2 items-center">
                      <span className="text-slate-400">{d.announcement_date}</span>
                      <div className="truncate">
                        <span className={`font-medium ${d.deal_type === 'M&A' ? 'text-violet-600' : d.deal_type === 'licensing' ? 'text-blue-600' : 'text-slate-600'}`}>
                          {d.deal_type}
                        </span>
                        {d.acquirer && <span className="text-slate-400 ml-1">by {d.acquirer}</span>}
                        {d.target && <span className="text-slate-400 ml-1">({d.target})</span>}
                      </div>
                      <span className="text-right font-mono text-slate-500">
                        {d.upfront_value_mm != null ? `$${d.upfront_value_mm}M` : '—'}
                      </span>
                      <span className="text-right font-mono text-slate-400">
                        {d.total_value_mm != null ? `$${d.total_value_mm}M` : '—'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>}
        </>}

        {/* BIOLOGICS */}
        {tab === 'bio' && <>
          {!purpleBook || !purpleBook.is_biologic_company ? (
            <div className="rounded-lg border border-dashed p-4 text-slate-400 text-center text-xs">
              {purpleBook?.status === 'no_data'
                ? 'No Purple Book data loaded. Run scripts/ingest_purple_book.py first.'
                : `No FDA-licensed biologics found for ${ticker}`}
            </div>
          ) : <>
            {/* Summary */}
            <div className="grid grid-cols-3 gap-1.5">
              <Stat label="products" value={String(purpleBook.n_products)} />
              <Stat label="reference" value={String(purpleBook.n_reference_products || 0)} />
              <Stat label="own biosimilars" value={String(purpleBook.n_own_biosimilars || 0)} />
              <Stat label="biosimilar threats" value={String(purpleBook.total_biosimilar_count)}
                accent={purpleBook.total_biosimilar_count > 0 ? '#ef4444' : '#22c55e'} />
              <Stat label="interchangeable" value={String(purpleBook.total_interchangeable_count)}
                accent={purpleBook.total_interchangeable_count > 0 ? '#ef4444' : '#22c55e'} />
              <Stat label="exclusivity expired" value={
                purpleBook.exclusivity_status?.some((e: any) => e.expired) ? 'YES' : 'NO'
              } accent={purpleBook.exclusivity_status?.some((e: any) => e.expired) ? '#ef4444' : '#22c55e'} />
            </div>

            {/* Biosimilar exposure */}
            {purpleBook.biosimilar_exposure?.length > 0 && (
              <div className="rounded-lg border overflow-hidden">
                <div className="bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700">
                  Biosimilar competition ({purpleBook.biosimilar_exposure.length} products exposed)
                </div>
                <div className="divide-y">
                  {purpleBook.biosimilar_exposure.map((exp: any, i: number) => (
                    <div key={i} className="px-3 py-2 text-xs">
                      <div className="font-medium">{exp.product_name || exp.bla_number}</div>
                      <div className="text-slate-500 mt-0.5">
                        {exp.biosimilar_count} biosimilar{exp.biosimilar_count !== 1 ? 's' : ''}
                        {exp.interchangeable_count > 0 && ` + ${exp.interchangeable_count} interchangeable`}
                      </div>
                      {exp.biosimilar_names?.length > 0 && (
                        <div className="text-slate-400 mt-0.5 text-[10px]">
                          {exp.biosimilar_names.filter(Boolean).join(', ')}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Exclusivity */}
            {purpleBook.exclusivity_status?.length > 0 && (
              <div className="rounded-lg border p-2">
                <div className="text-xs font-medium mb-1">Exclusivity status</div>
                <div className="space-y-0.5">
                  {purpleBook.exclusivity_status.map((ex: any, i: number) => (
                    <div key={i} className="flex justify-between text-xs">
                      <span className="text-slate-600">{ex.product_name}</span>
                      <span className={`font-mono ${ex.expired ? 'text-rose-500' : 'text-emerald-500'}`}>
                        {ex.exclusivity_expiry_date} {ex.expired ? '(expired)' : '(active)'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Product list */}
            {purpleBook.products?.length > 0 && (
              <div className="rounded-lg border overflow-hidden">
                <div className="bg-slate-50 px-3 py-1.5 text-xs font-medium">Licensed products</div>
                <div className="divide-y max-h-[200px] overflow-auto">
                  {purpleBook.products.map((p: any, i: number) => (
                    <div key={i} className="px-3 py-1.5 text-xs flex justify-between items-center">
                      <div className="truncate">
                        <span className="font-medium">{p.product_name || p.nonproprietary_name || p.bla_number}</span>
                        {p.is_biosimilar && <span className="ml-1 text-[10px] px-1 rounded bg-blue-50 text-blue-600">biosimilar</span>}
                        {p.is_interchangeable && <span className="ml-1 text-[10px] px-1 rounded bg-violet-50 text-violet-600">interchangeable</span>}
                      </div>
                      <span className="text-slate-400 font-mono text-[10px]">{p.licensing_date || '—'}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>}
        </>}

        {/* CRT */}
        {tab === 'crt' && <>
          {crt.length === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-slate-400 text-center">No CRT history for {ticker}</div>
          ) : <>
            {crtBars.length > 0 && (
              <div className="h-28">
                <ResponsiveContainer>
                  <BarChart data={crtBars} margin={{ top: 2, right: 5, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="name" tick={{ fontSize: 8 }} />
                    <YAxis tick={{ fontSize: 9 }} domain={[-1, 1]} />
                    <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                      {crtBars.map((b: any, i: number) => <Cell key={i} fill={b.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <div className="space-y-1.5">
              {crt.map((c: any, i: number) => (
                <div key={i} className={`flex justify-between items-center rounded-lg px-3 py-2 ${outcomeBg[c.outcome] || 'bg-slate-50'}`}>
                  <div>
                    <div className="font-semibold text-xs">{c.outcome}</div>
                    <div className="text-[10px] opacity-70">rank: {c.prediction_dem_rank ?? 'unranked'} · {c.catalyst_date}</div>
                  </div>
                  <div className="text-xs font-medium">{c.price_direction || '—'}</div>
                </div>
              ))}
            </div>
          </>}
        </>}
      </div>
    </div>
  );
}
