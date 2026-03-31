import { useEffect, useState } from 'react';
import { Shield, AlertTriangle, CheckCircle } from 'lucide-react';
import { fetchBioshortVerdict, fetchBioshortReport, fetchBioshortWatch } from './api';

const verdictStyle: Record<string, string> = {
  'HEDGE NOW': 'bg-rose-50 border-rose-200 text-rose-800',
  'WATCH': 'bg-amber-50 border-amber-200 text-amber-800',
  'DEFER': 'bg-emerald-50 border-emerald-200 text-emerald-700',
};

const verdictIcon: Record<string, any> = {
  'HEDGE NOW': AlertTriangle,
  'WATCH': Shield,
  'DEFER': CheckCircle,
};

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3">
      <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      {sub && <div className="text-xs text-slate-400 mt-0.5">{sub}</div>}
    </div>
  );
}

export default function BioshortPanel() {
  const [verdict, setVerdict] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [watch, setWatch] = useState<any>(null);

  useEffect(() => {
    fetchBioshortVerdict().then(setVerdict);
    fetchBioshortReport().then(setReport);
    fetchBioshortWatch().then(setWatch);
  }, []);

  if (!verdict || verdict.error) {
    return <div className="p-8 text-slate-400 text-center">No bioshort data available</div>;
  }

  const Icon = verdictIcon[verdict.verdict] || Shield;
  const style = verdictStyle[verdict.verdict] || 'bg-slate-50 border-slate-200';
  const ev = verdict.evidence || {};

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* Verdict banner */}
      <div className={`p-4 border-b ${style} border`}>
        <div className="flex items-center gap-3">
          <Icon className="h-6 w-6" />
          <div>
            <div className="text-xl font-bold">{verdict.verdict}</div>
            <div className="text-sm opacity-80">{verdict.recommendation}</div>
          </div>
        </div>
        <div className="mt-2 flex items-center gap-4 text-sm">
          <span>Confidence: <strong>{verdict.confidence}</strong> ({verdict.confidence_score})</span>
          <span>As of: <strong>{verdict.as_of_date}</strong></span>
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 p-4">
        <Stat label="Carry (bps)" value={`${ev.primary_cost_bps ?? '—'}`} sub="Lower is cheaper" />
        <Stat label="Score" value={`${ev.primary_score?.toFixed(1) ?? '—'}`} sub="Higher is better" />
        <Stat label="Best vehicle" value={ev.best_vehicle || '—'} sub={`R² = ${ev.best_vehicle_r_squared?.toFixed(3) ?? '—'}`} />
        <Stat label="Historical months" value={`${ev.historical_months ?? '—'} / ${ev.total_months ?? '—'}`} sub="Backtest coverage" />
      </div>

      {/* Policy reasons */}
      <div className="px-4 pb-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Policy reasons</div>
        <div className="space-y-1.5">
          {(verdict.policy_reasons || []).map((r: string, i: number) => (
            <div key={i} className="rounded-lg bg-slate-50 px-3 py-2 text-sm">{r}</div>
          ))}
        </div>
      </div>

      {/* Confidence drivers */}
      <div className="px-4 pb-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Confidence drivers</div>
        <div className="space-y-1.5">
          {(verdict.confidence_drivers || []).map((r: string, i: number) => (
            <div key={i} className="rounded-lg bg-slate-50 px-3 py-2 text-sm">{r}</div>
          ))}
        </div>
      </div>

      {/* Report detail */}
      {report && !report.error && (
        <div className="px-4 pb-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Report detail</div>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Hedge notional" value={`$${((report.hedge_notional || 0) / 1000).toFixed(0)}K`} />
            <Stat label="Options source" value={report.options_source_used || '—'} />
            <Stat label="Beta to XBI" value={report.beta_stats?.beta?.toFixed(2) ?? '—'} sub={`corr = ${report.beta_stats?.correlation?.toFixed(2) ?? '—'}`} />
            <Stat label="Backtest months" value={`${report.backtest_months ?? '—'}`} />
          </div>

          {/* Top structures */}
          {report.ranked_structures && (
            <div className="mt-3">
              <div className="text-xs font-medium text-slate-500 mb-1.5">Ranked structures (top 5)</div>
              <div className="space-y-1.5">
                {report.ranked_structures.slice(0, 5).map((s: any, i: number) => (
                  <div key={i} className="flex justify-between items-center rounded-lg bg-slate-50 px-3 py-2 text-sm">
                    <div>
                      <span className="font-medium">{s.vehicle} {s.structure_type}</span>
                      <span className="text-slate-400 ml-2">{s.moneyness}</span>
                    </div>
                    <div className="text-right">
                      <span className="font-mono">{s.score?.toFixed(1)}</span>
                      <span className="text-slate-400 text-xs ml-1">score</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Watch alerts */}
      {watch && !watch.error && watch.alerts && (
        <div className="px-4 pb-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Watch alerts ({watch.alert_level})
          </div>
          <div className="space-y-1.5">
            {watch.alerts.map((a: string, i: number) => (
              <div key={i} className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-sm text-amber-800">
                {a}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
