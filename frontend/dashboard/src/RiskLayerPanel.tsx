import { useEffect, useState } from 'react';
import { fetchRiskLayerLatest, fetchRebalancePlanLatest } from './api';

interface Breach {
  control: string;
  ticker: string;
  detail: string;
  action: string;
}

interface Flag {
  flag_type: string;
  ticker: string;
  severity: string;
  detail: string;
}

export default function RiskLayerPanel() {
  const [rl, setRl] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchRiskLayerLatest(), fetchRebalancePlanLatest()]).then(
      ([r, p]) => {
        setRl(r?.error ? null : r);
        setPlan(p?.error ? null : p);
        setLoading(false);
      }
    );
  }, []);

  if (loading) return <div className="text-xs text-slate-400 p-4">Loading risk layer...</div>;
  if (!rl && !plan) return <div className="text-xs text-slate-400 p-4">No risk layer data</div>;

  const breaches: Breach[] = rl?.breaches || [];
  const flags: Flag[] = rl?.flags || [];
  const nBreaches = rl?.n_breaches || breaches.length;
  const effectiveCap = rl?.effective_cap_pct;
  const isDrawdownActive = effectiveCap && effectiveCap < 0.03;

  // Group breaches by control
  const byControl: Record<string, Breach[]> = {};
  breaches.forEach((b) => {
    if (!byControl[b.control]) byControl[b.control] = [];
    byControl[b.control].push(b);
  });

  // Rebalance plan summary
  const buys = plan?.buys || [];
  const sells = plan?.sells || [];
  const skip = plan?.skip_rebalance;
  const skipReason = plan?.skip_reason;
  const turnover = plan?.one_way_turnover;
  const tradeCost = plan?.est_trade_cost_usd;

  // Vol/corr metrics from risk monitor v2
  const metrics = rl?.metrics || {};
  const portVol = metrics.portfolio_vol_60d_annualized;
  const volTarget = metrics.vol_target;
  const volBreach = metrics.vol_breach;
  const avgCorr = metrics.avg_pairwise_corr_60d;
  const maxCluster = metrics.max_cluster_size;
  const highCorrPairs = metrics.top_high_corr_pairs || [];

  const controlLabel: Record<string, string> = {
    C1_single_name_cap: 'Name Cap',
    C2_therapeutic_area_cap: 'Area Cap',
    C3_liquidity_ceiling: 'Liquidity',
    C4_drawdown_breaker: 'Drawdown',
    C5_correlated_pair_limit: 'Pair Limit',
    C6_vol_target: 'Vol Target',
    C7_corr_cluster_limit: 'Corr Cluster',
  };

  const controlColor: Record<string, string> = {
    C1_single_name_cap: 'bg-sky-100 text-sky-700',
    C2_therapeutic_area_cap: 'bg-violet-100 text-violet-700',
    C3_liquidity_ceiling: 'bg-amber-100 text-amber-700',
    C4_drawdown_breaker: 'bg-rose-100 text-rose-700',
    C5_correlated_pair_limit: 'bg-orange-100 text-orange-700',
    C6_vol_target: 'bg-indigo-100 text-indigo-700',
    C7_corr_cluster_limit: 'bg-teal-100 text-teal-700',
  };

  return (
    <div className="p-4 space-y-4 overflow-auto h-full">
      <h2 className="text-sm font-semibold text-slate-700">Risk Layer + Rebalance</h2>

      {/* Status banner */}
      <div className={`rounded-lg px-3 py-2 text-xs font-medium flex items-center justify-between ${
        isDrawdownActive ? 'bg-rose-50 text-rose-800 border border-rose-200'
        : nBreaches > 0 ? 'bg-amber-50 text-amber-800 border border-amber-200'
        : 'bg-emerald-50 text-emerald-800 border border-emerald-200'
      }`}>
        <span>
          {isDrawdownActive ? 'DRAWDOWN BREAKER ACTIVE' : nBreaches > 0 ? `${nBreaches} constraint${nBreaches > 1 ? 's' : ''} binding` : 'All constraints OK'}
        </span>
        {effectiveCap && (
          <span className="text-[10px] opacity-70">
            effective cap: {(effectiveCap * 100).toFixed(1)}%
          </span>
        )}
      </div>

      {/* Vol / Corr metrics */}
      {portVol != null && (
        <div className="grid grid-cols-4 gap-2 text-[10px]">
          <div className="bg-slate-50 rounded px-2 py-1.5">
            <div className="text-slate-400 font-medium">Portfolio Vol</div>
            <div className={`text-lg font-semibold ${volBreach ? 'text-rose-600' : 'text-slate-700'}`}>
              {(portVol * 100).toFixed(0)}%
            </div>
          </div>
          <div className="bg-slate-50 rounded px-2 py-1.5">
            <div className="text-slate-400 font-medium">Vol Target</div>
            <div className="text-lg font-semibold text-slate-700">{volTarget ? (volTarget * 100).toFixed(0) : '—'}%</div>
          </div>
          <div className="bg-slate-50 rounded px-2 py-1.5">
            <div className="text-slate-400 font-medium">Avg Corr</div>
            <div className="text-lg font-semibold text-slate-700">{avgCorr != null ? avgCorr.toFixed(2) : '—'}</div>
          </div>
          <div className="bg-slate-50 rounded px-2 py-1.5">
            <div className="text-slate-400 font-medium">Max Cluster</div>
            <div className={`text-lg font-semibold ${maxCluster > 3 ? 'text-amber-600' : 'text-slate-700'}`}>
              {maxCluster ?? '—'}
            </div>
          </div>
        </div>
      )}

      {highCorrPairs.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">High Correlation Pairs</div>
          <div className="grid grid-cols-[auto_auto_1fr] gap-x-3 gap-y-0.5 text-[10px] pl-2">
            {highCorrPairs.slice(0, 5).map((p: any, i: number) => (
              <Fragment key={i}>
                <span className="font-mono font-semibold text-slate-700">{p[0]}</span>
                <span className="font-mono font-semibold text-slate-700">{p[1]}</span>
                <span className="text-slate-500">{(p[2]).toFixed(2)}</span>
              </Fragment>
            ))}
          </div>
        </div>
      )}

      {/* Breaches by control */}
      {Object.entries(byControl).length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Active Constraints</div>
          {Object.entries(byControl).map(([ctrl, items]) => (
            <div key={ctrl} className="space-y-1">
              <div className="flex items-center gap-2">
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${controlColor[ctrl] || 'bg-slate-100 text-slate-600'}`}>
                  {controlLabel[ctrl] || ctrl}
                </span>
                <span className="text-[10px] text-slate-400">{items.length} name{items.length > 1 ? 's' : ''}</span>
              </div>
              <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[10px] pl-2">
                {items.slice(0, 5).map((b, i) => (
                  <Fragment key={i}>
                    <span className="font-mono font-semibold text-slate-700">{b.ticker}</span>
                    <span className="text-slate-500 truncate">{b.detail}</span>
                  </Fragment>
                ))}
                {items.length > 5 && (
                  <>
                    <span />
                    <span className="text-slate-400 italic">+{items.length - 5} more</span>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Flags */}
      {flags.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Flags</div>
          {flags.slice(0, 8).map((f, i) => (
            <div key={i} className="flex items-center gap-2 text-[10px]">
              <span className={`px-1.5 py-0.5 rounded font-semibold ${
                f.severity === 'WARN' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'
              }`}>{f.flag_type.replace(/_/g, ' ')}</span>
              <span className="font-mono text-slate-700">{f.ticker}</span>
              <span className="text-slate-400 truncate">{f.detail}</span>
            </div>
          ))}
        </div>
      )}

      {/* Divider */}
      <hr className="border-slate-200" />

      {/* Rebalance plan */}
      {plan && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Rebalance Plan</div>
            {skip ? (
              <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-semibold">
                SKIP: {skipReason}
              </span>
            ) : (
              <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded font-semibold">
                EXECUTE
              </span>
            )}
          </div>

          <div className="grid grid-cols-4 gap-2 text-[10px]">
            <div className="bg-slate-50 rounded px-2 py-1.5">
              <div className="text-slate-400 font-medium">Target</div>
              <div className="text-lg font-semibold text-slate-700">{plan.target_count}</div>
            </div>
            <div className="bg-slate-50 rounded px-2 py-1.5">
              <div className="text-slate-400 font-medium">Turnover</div>
              <div className="text-lg font-semibold text-slate-700">{turnover ? (turnover * 100).toFixed(0) : '—'}%</div>
            </div>
            <div className="bg-slate-50 rounded px-2 py-1.5">
              <div className="text-slate-400 font-medium">Buys</div>
              <div className="text-lg font-semibold text-emerald-600">{buys.length}</div>
            </div>
            <div className="bg-slate-50 rounded px-2 py-1.5">
              <div className="text-slate-400 font-medium">Sells</div>
              <div className="text-lg font-semibold text-rose-600">{sells.length}</div>
            </div>
          </div>

          {(buys.length > 0 || sells.length > 0) && (
            <div className="grid grid-cols-2 gap-3 text-[10px]">
              {buys.length > 0 && (
                <div>
                  <div className="font-semibold text-emerald-600 mb-0.5">BUY</div>
                  <div className="space-y-0.5">
                    {buys.map((t: string) => (
                      <div key={t} className="font-mono text-slate-700">{t}</div>
                    ))}
                  </div>
                </div>
              )}
              {sells.length > 0 && (
                <div>
                  <div className="font-semibold text-rose-600 mb-0.5">SELL</div>
                  <div className="space-y-0.5">
                    {sells.map((t: string) => (
                      <div key={t} className="font-mono text-slate-700">{t}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {tradeCost != null && tradeCost > 0 && (
            <div className="text-[10px] text-slate-400">
              Est. trade cost: ${tradeCost.toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Fragment helper for grid rendering
function Fragment({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
