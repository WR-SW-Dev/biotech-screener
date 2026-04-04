import { useEffect, useState } from 'react';
import { fetchTimingHazardLatest, fetchEventQualityShadowLatest } from './api';

/* ── Confidence badge ─────────────────────────────────────────── */

function ConfBadge({ bucket }: { bucket: string }) {
  const cls =
    bucket === 'HIGH' ? 'bg-emerald-100 text-emerald-700' :
    bucket === 'MEDIUM' ? 'bg-amber-100 text-amber-700' :
    bucket === 'LOW' ? 'bg-rose-100 text-rose-700' :
    bucket === 'STALE' ? 'bg-slate-200 text-slate-600' :
    'bg-slate-100 text-slate-500';
  return <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${cls}`}>{bucket}</span>;
}

/* ── Warning badge ────────────────────────────────────────────── */

function WarningBadge({ reasons }: { reasons: string[] }) {
  if (!reasons || reasons.length === 0) return null;
  return (
    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700">
      {reasons.join(', ')}
    </span>
  );
}

/* ── Tilt badge ───────────────────────────────────────────────── */

function TiltBadge({ reason, tilt }: { reason: string; tilt: number }) {
  if (tilt === 1.0) return <span className="text-[10px] text-slate-400">-</span>;
  const cls = tilt > 1.0 ? 'text-emerald-600' : 'text-rose-600';
  const arrow = tilt > 1.0 ? '\u2191' : '\u2193';
  return (
    <span className={`text-[10px] font-medium ${cls}`}>
      {arrow}{((tilt - 1) * 100).toFixed(0)}% {reason}
    </span>
  );
}

/* ── Main Panel ───────────────────────────────────────────────── */

export default function TimingHazardPanel() {
  const [hazard, setHazard] = useState<any>(null);
  const [eqShadow, setEqShadow] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchTimingHazardLatest(),
      fetchEventQualityShadowLatest(),
    ]).then(([h, eq]) => {
      setHazard(h);
      setEqShadow(eq);
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="text-sm text-slate-400 p-4">Loading timing hazard...</div>;

  return (
    <div className="space-y-4">
      {/* Timing Hazard Card */}
      {hazard && !hazard.error && (
        <div className="rounded-lg border bg-white p-4">
          <div className="flex justify-between items-center mb-3">
            <div>
              <h3 className="text-sm font-semibold">Timing Hazard Overlay</h3>
              <p className="text-[10px] text-slate-400">
                Per-catalyst slip probability &mdash; {hazard.snapshot_date}
              </p>
            </div>
            <div className="flex gap-3 items-center">
              <span className="text-xs text-slate-500">{hazard.n_catalysts} catalysts</span>
              {hazard.n_warnings > 0 && (
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-rose-100 text-rose-700">
                  {hazard.n_warnings} warnings
                </span>
              )}
            </div>
          </div>

          {/* KPI row */}
          <div className="grid grid-cols-5 gap-3 mb-4">
            <div className="text-center">
              <div className="text-lg font-bold text-slate-700">{hazard.n_catalysts}</div>
              <div className="text-[10px] text-slate-400">Catalysts</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-emerald-600">{hazard.confidence_dist?.HIGH || 0}</div>
              <div className="text-[10px] text-slate-400">HIGH conf</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-amber-600">{hazard.confidence_dist?.MEDIUM || 0}</div>
              <div className="text-[10px] text-slate-400">MEDIUM</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-rose-600">{hazard.confidence_dist?.LOW || 0}</div>
              <div className="text-[10px] text-slate-400">LOW</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-slate-500">{hazard.confidence_dist?.STALE || 0}</div>
              <div className="text-[10px] text-slate-400">STALE</div>
            </div>
          </div>

          {/* Catalyst table */}
          <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50">
                <tr className="text-left text-[10px] text-slate-500 uppercase tracking-wider">
                  <th className="py-1.5 px-2">Ticker</th>
                  <th className="py-1.5 px-2 text-right">Rank</th>
                  <th className="py-1.5 px-2 text-right">Days</th>
                  <th className="py-1.5 px-2">Type</th>
                  <th className="py-1.5 px-2 text-right">P(on time)</th>
                  <th className="py-1.5 px-2 text-right">Slip 30d</th>
                  <th className="py-1.5 px-2 text-right">Slip 60d+</th>
                  <th className="py-1.5 px-2">Conf</th>
                  <th className="py-1.5 px-2 text-right">Upd Age</th>
                  <th className="py-1.5 px-2">Warning</th>
                </tr>
              </thead>
              <tbody>
                {(hazard.catalysts || []).map((cat: any) => (
                  <tr
                    key={cat.ticker}
                    className={`border-t hover:bg-slate-50 ${cat.execution_warning_flag ? 'bg-rose-50' : ''}`}
                  >
                    <td className="py-1.5 px-2 font-medium">{cat.ticker}</td>
                    <td className="py-1.5 px-2 text-right text-slate-500">{cat.rank}</td>
                    <td className="py-1.5 px-2 text-right">{cat.catalyst_days}</td>
                    <td className="py-1.5 px-2 text-slate-500">{cat.catalyst_event_type}</td>
                    <td className={`py-1.5 px-2 text-right font-mono ${
                      cat.on_time_prob >= 0.7 ? 'text-emerald-600' :
                      cat.on_time_prob >= 0.45 ? 'text-amber-600' : 'text-rose-600'
                    }`}>
                      {(cat.on_time_prob * 100).toFixed(0)}%
                    </td>
                    <td className="py-1.5 px-2 text-right font-mono text-slate-500">
                      {(cat.slip_prob_30d * 100).toFixed(0)}%
                    </td>
                    <td className="py-1.5 px-2 text-right font-mono text-slate-500">
                      {(cat.slip_prob_60d_plus * 100).toFixed(0)}%
                    </td>
                    <td className="py-1.5 px-2"><ConfBadge bucket={cat.timing_confidence_bucket} /></td>
                    <td className="py-1.5 px-2 text-right text-slate-500">
                      {cat.last_update_age != null ? `${cat.last_update_age}d` : '-'}
                    </td>
                    <td className="py-1.5 px-2">
                      <WarningBadge reasons={cat.warning_reasons || []} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Event Quality Shadow Card */}
      {eqShadow && !eqShadow.error && (
        <div className="rounded-lg border bg-white p-4">
          <div className="flex justify-between items-center mb-3">
            <div>
              <h3 className="text-sm font-semibold">Event Quality Shadow Sizing</h3>
              <p className="text-[10px] text-slate-400">
                Position tilts from catalyst quality &mdash; {eqShadow.snapshot_date}
              </p>
            </div>
            <div className="flex gap-3 items-center">
              <span className="text-[10px] text-emerald-600 font-medium">
                {eqShadow.n_upweighted} up
              </span>
              <span className="text-[10px] text-rose-600 font-medium">
                {eqShadow.n_downweighted} down
              </span>
              <span className="text-[10px] text-slate-400">
                {eqShadow.n_unchanged} unchanged
              </span>
            </div>
          </div>

          {/* Tilt counts */}
          {eqShadow.tilt_counts && (
            <div className="flex gap-3 mb-3">
              {Object.entries(eqShadow.tilt_counts as Record<string, number>).map(([k, v]) => (
                <span key={k} className="text-[10px] text-slate-500">
                  {k}: <strong>{v as number}</strong>
                </span>
              ))}
            </div>
          )}

          {/* Position table — only show tilted positions */}
          <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50">
                <tr className="text-left text-[10px] text-slate-500 uppercase tracking-wider">
                  <th className="py-1.5 px-2">Ticker</th>
                  <th className="py-1.5 px-2 text-right">Rank</th>
                  <th className="py-1.5 px-2 text-right">Prod Wt%</th>
                  <th className="py-1.5 px-2 text-right">Shadow Wt%</th>
                  <th className="py-1.5 px-2 text-right">Delta</th>
                  <th className="py-1.5 px-2">Tilt</th>
                </tr>
              </thead>
              <tbody>
                {(eqShadow.positions || [])
                  .filter((p: any) => p.event_quality_tilt !== 1.0)
                  .map((p: any) => (
                    <tr key={p.ticker} className="border-t hover:bg-slate-50">
                      <td className="py-1.5 px-2 font-medium">{p.ticker}</td>
                      <td className="py-1.5 px-2 text-right text-slate-500">{p.rank}</td>
                      <td className="py-1.5 px-2 text-right font-mono">{p.production_weight_pct?.toFixed(2)}</td>
                      <td className="py-1.5 px-2 text-right font-mono">{p.shadow_weight_pct?.toFixed(2)}</td>
                      <td className={`py-1.5 px-2 text-right font-mono ${
                        p.weight_delta_pct > 0 ? 'text-emerald-600' : p.weight_delta_pct < 0 ? 'text-rose-600' : ''
                      }`}>
                        {p.weight_delta_pct > 0 ? '+' : ''}{p.weight_delta_pct?.toFixed(2)}
                      </td>
                      <td className="py-1.5 px-2">
                        <TiltBadge reason={p.tilt_reason} tilt={p.event_quality_tilt} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
