import { useEffect, useState } from 'react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  BarChart, Bar,
} from 'recharts';
import {
  fetchCoinvestShadowHistory, fetchCoinvestShadowLatest,
  fetchRegimeShadowHistory,
  fetchConstructionV2Performance,
  fetchPostPromotionMonitor,
} from './api';
import TimingHazardPanel from './TimingHazardPanel';

/* ── Regime badge ─────────────────────────────────────────────── */

function RegimeBadge({ regime }: { regime: string | null }) {
  if (!regime) return <span className="text-xs text-slate-400">—</span>;
  const r = regime.toUpperCase();
  const cls = r.includes('BEAR') ? 'bg-rose-100 text-rose-700'
    : r.includes('BULL') ? 'bg-emerald-100 text-emerald-700'
    : 'bg-amber-100 text-amber-700';
  return <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${cls}`}>{r}</span>;
}

/* ── Coinvest Shadow card ─────────────────────────────────────── */

function CoinvestShadow() {
  const [history, setHistory] = useState<any[]>([]);
  const [latest, setLatest] = useState<any>(null);

  useEffect(() => {
    fetchCoinvestShadowHistory().then(setHistory);
    fetchCoinvestShadowLatest().then(setLatest);
  }, []);

  const chartData = history.map((r: any) => ({
    date: r.date,
    ci_overlap: parseFloat(r.coinvest_inst_overlap_pct || '0'),
    ri_overlap: parseFloat(r.resid_inst_overlap_pct || '0'),
    ci_turnover: parseFloat(r.coinvest_inst_turnover || '0') * 100,
    ri_turnover: parseFloat(r.resid_inst_turnover || '0') * 100,
    regime: r.regime,
  }));

  const strategies = latest?.strategies || {};
  const ciOverlap = strategies.coinvest_inst?.overlap_pct;
  const riOverlap = strategies.resid_inst?.overlap_pct;
  const day = latest?.days_since_start;

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex justify-between items-center mb-3">
        <div>
          <h3 className="text-sm font-semibold">Coinvest Anchor Shadow</h3>
          <p className="text-[10px] text-slate-400">30-day validation — coinvest+inst vs DEM baseline</p>
        </div>
        <div className="flex gap-3 items-center">
          {day != null && (
            <span className="text-xs text-slate-500">Day {day}/30</span>
          )}
          <RegimeBadge regime={latest?.regime} />
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <div className="text-center">
          <div className="text-lg font-bold text-indigo-600">{ciOverlap != null ? `${ciOverlap}%` : '—'}</div>
          <div className="text-[10px] text-slate-400">CI Overlap</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-violet-600">{riOverlap != null ? `${riOverlap}%` : '—'}</div>
          <div className="text-[10px] text-slate-400">RI Overlap</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-700">{history.length}</div>
          <div className="text-[10px] text-slate-400">Days tracked</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-700">{latest?.n_eligible || '—'}</div>
          <div className="text-[10px] text-slate-400">Eligible</div>
        </div>
      </div>

      {/* Overlap chart */}
      {chartData.length > 1 && (
        <div className="h-40 mb-3">
          <div className="text-[10px] text-slate-400 mb-1">Overlap with DEM baseline (%)</div>
          <ResponsiveContainer>
            <LineChart data={chartData} margin={{ left: 0, right: 5, top: 2, bottom: 2 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 8 }} />
              <YAxis tick={{ fontSize: 9 }} domain={[0, 100]} tickFormatter={(v) => `${v}%`} width={35} />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
              <Line type="monotone" dataKey="ci_overlap" stroke="#6366f1" strokeWidth={2} dot name="Coinvest+Inst" />
              <Line type="monotone" dataKey="ri_overlap" stroke="#8b5cf6" strokeWidth={2} dot name="Resid+Inst" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Turnover chart */}
      {chartData.filter(d => d.ci_turnover > 0).length > 0 && (
        <div className="h-32">
          <div className="text-[10px] text-slate-400 mb-1">Daily turnover (%)</div>
          <ResponsiveContainer>
            <BarChart data={chartData} margin={{ left: 0, right: 5, top: 2, bottom: 2 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 8 }} />
              <YAxis tick={{ fontSize: 9 }} tickFormatter={(v) => `${v}%`} width={35} />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
              <Bar dataKey="ci_turnover" fill="#6366f1" name="CI Turnover" />
              <Bar dataKey="ri_turnover" fill="#8b5cf6" name="RI Turnover" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Top-30 diff */}
      {latest?.selections && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          <div>
            <div className="text-[10px] font-medium text-slate-500 mb-1">CI-only (not in baseline)</div>
            <div className="flex flex-wrap gap-1">
              {(() => {
                const base = new Set(latest.selections.baseline || []);
                const ci = latest.selections.coinvest_inst || [];
                return ci.filter((t: string) => !base.has(t)).slice(0, 12).map((t: string) => (
                  <span key={t} className="text-[10px] bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded">{t}</span>
                ));
              })()}
            </div>
          </div>
          <div>
            <div className="text-[10px] font-medium text-slate-500 mb-1">Baseline-only (not in CI)</div>
            <div className="flex flex-wrap gap-1">
              {(() => {
                const ci = new Set(latest.selections.coinvest_inst || []);
                const base = latest.selections.baseline || [];
                return base.filter((t: string) => !ci.has(t)).slice(0, 12).map((t: string) => (
                  <span key={t} className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">{t}</span>
                ));
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Regime Shadow card ───────────────────────────────────────── */

function RegimeShadow() {
  const [history, setHistory] = useState<any[]>([]);

  useEffect(() => {
    fetchRegimeShadowHistory().then(setHistory);
  }, []);

  if (history.length === 0) return null;
  const latest = history[history.length - 1];

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex justify-between items-center mb-3">
        <div>
          <h3 className="text-sm font-semibold">Regime Shadow</h3>
          <p className="text-[10px] text-slate-400">Simple vs rich classifier — switching policy frozen</p>
        </div>
        <div className="flex gap-2 items-center">
          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${latest.agreement ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
            {latest.agreement ? 'AGREE' : 'DISAGREE'}
          </span>
          <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
            {latest.recommendation?.toUpperCase() || '—'}
          </span>
        </div>
      </div>

      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-slate-400 border-b">
            <th className="py-1 font-medium">Date</th>
            <th className="py-1 font-medium">Simple</th>
            <th className="py-1 font-medium">Rich</th>
            <th className="py-1 font-medium">Conf</th>
            <th className="py-1 font-medium">Agree</th>
            <th className="py-1 font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {history.slice(-10).reverse().map((r: any) => (
            <tr key={r.date} className="border-b border-slate-50">
              <td className="py-1 text-slate-600">{r.date}</td>
              <td className="py-1"><RegimeBadge regime={r.simple_regime} /></td>
              <td className="py-1"><RegimeBadge regime={r.rich_regime} /></td>
              <td className="py-1 text-slate-500">{r.rich_confidence != null ? (r.rich_confidence * 1).toFixed(2) : '—'}</td>
              <td className="py-1">
                <span className={r.agreement ? 'text-emerald-600' : 'text-amber-600'}>{r.agreement ? 'Y' : 'N'}</span>
              </td>
              <td className="py-1 text-slate-500">{r.recommendation || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Construction v2 Shadow card ──────────────────────────────── */

function ConstructionV2Shadow() {
  const [data, setData] = useState<any[]>([]);

  useEffect(() => {
    fetchConstructionV2Performance().then(setData);
  }, []);

  if (data.length === 0) return null;
  const latest = data[data.length - 1];

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex justify-between items-center mb-3">
        <div>
          <h3 className="text-sm font-semibold">Construction v2 Shadow</h3>
          <p className="text-[10px] text-slate-400">EW30 vs regime-switched — cumulative excess vs XBI</p>
        </div>
        <div className="flex gap-3 text-[10px]">
          <span className="text-indigo-600 font-semibold">
            EW30 {parseFloat(latest.cum_ew30_excess || 0) > 0 ? '+' : ''}{(parseFloat(latest.cum_ew30_excess || 0) * 100).toFixed(1)}%
          </span>
          <span className="text-violet-600 font-semibold">
            Regime {parseFloat(latest.cum_regime_excess || 0) > 0 ? '+' : ''}{(parseFloat(latest.cum_regime_excess || 0) * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      <div className="h-40">
        <ResponsiveContainer>
          <LineChart data={data.slice(-60)} margin={{ left: 0, right: 5, top: 2, bottom: 2 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="date" tick={{ fontSize: 8 }} interval={Math.floor(data.slice(-60).length / 5)} />
            <YAxis tick={{ fontSize: 9 }} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} width={40} />
            <Tooltip
              contentStyle={{ fontSize: 11, borderRadius: 8 }}
              formatter={(v: any) => [`${(v * 100).toFixed(2)}%`]}
            />
            <Line type="monotone" dataKey="cum_ew30_excess" stroke="#6366f1" strokeWidth={2} dot={false} name="EW30 Excess" />
            <Line type="monotone" dataKey="cum_regime_excess" stroke="#8b5cf6" strokeWidth={1.5} dot={false} strokeDasharray="4 4" name="Regime Excess" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ── Post-promotion monitor card ──────────────────────────────── */

function PostPromotionMonitor() {
  const [monitors, setMonitors] = useState<any[]>([]);

  useEffect(() => {
    fetchPostPromotionMonitor().then(setMonitors);
  }, []);

  if (monitors.length === 0) return null;
  const latest = monitors[monitors.length - 1];
  const perf = latest.performance_since_promotion || {};

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex justify-between items-center mb-3">
        <div>
          <h3 className="text-sm font-semibold">Post-Promotion Monitor</h3>
          <p className="text-[10px] text-slate-400">
            EW30 promoted {latest.promotion_date} — day {latest.days_since_promotion}/30
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <RegimeBadge regime={latest.regime} />
          {latest.alerts && latest.alerts.length > 0 && (
            <span className="text-[10px] bg-rose-100 text-rose-700 px-1.5 py-0.5 rounded font-semibold">
              {latest.alerts.length} alert{latest.alerts.length > 1 ? 's' : ''}
            </span>
          )}
          {latest.alerts && latest.alerts.length === 0 && (
            <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded">OK</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        <div className="text-center">
          <div className="text-lg font-bold text-slate-700">{latest.n_positions || '—'}</div>
          <div className="text-[10px] text-slate-400">Positions</div>
        </div>
        <div className="text-center">
          <div className={`text-lg font-bold ${(perf.cum_excess_pct || 0) >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
            {perf.cum_excess_pct != null ? `${perf.cum_excess_pct > 0 ? '+' : ''}${perf.cum_excess_pct.toFixed(2)}%` : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Cum excess</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-700">{perf.n_days || latest.days_since_promotion || '—'}</div>
          <div className="text-[10px] text-slate-400">Days</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-700">{latest.construction_mode || '—'}</div>
          <div className="text-[10px] text-slate-400">Mode</div>
        </div>
      </div>

      {latest.alerts && latest.alerts.length > 0 && (
        <div className="mt-3 space-y-1">
          {latest.alerts.map((a: any, i: number) => (
            <div key={i} className="text-[10px] bg-rose-50 text-rose-700 px-2 py-1 rounded">
              {typeof a === 'string' ? a : a.message || JSON.stringify(a)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main panel ───────────────────────────────────────────────── */

export default function ShadowsPanel() {
  return (
    <div className="max-w-5xl mx-auto py-6 px-4 space-y-4">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h2 className="text-lg font-semibold">Shadow Monitors</h2>
          <p className="text-xs text-slate-400">All shadow comparators and validation monitors</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <CoinvestShadow />
        <PostPromotionMonitor />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <ConstructionV2Shadow />
        <RegimeShadow />
      </div>

      <TimingHazardPanel />
    </div>
  );
}
