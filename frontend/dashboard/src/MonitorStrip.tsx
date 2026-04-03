import { useEffect, useState } from 'react';
import { fetchPostPromotionMonitorLatest, fetchCoinvestShadowLatest, fetchRegimeShadowLatest } from './api';

export default function MonitorStrip() {
  const [pm, setPm] = useState<any>(null);
  const [cs, setCs] = useState<any>(null);
  const [rs, setRs] = useState<any>(null);

  useEffect(() => {
    fetchPostPromotionMonitorLatest().then(setPm);
    fetchCoinvestShadowLatest().then(setCs);
    fetchRegimeShadowLatest().then(setRs);
  }, []);

  const pmDay = pm?.days_since_promotion;
  const pmAlerts = pm?.alerts?.length || 0;
  const csDay = cs?.days_since_start;
  const csOverlap = cs?.strategies?.coinvest_inst?.overlap_pct;
  const simpleRegime = rs?.simple_classifier?.regime;
  const richRegime = rs?.rich_classifier?.regime;
  const agree = rs?.agreement;

  // Don't show until at least one data source loads
  if (!pm && !cs && !rs) return null;

  return (
    <div className="flex gap-4 items-center text-[10px] bg-slate-50 border rounded-lg px-3 py-1.5 mb-2">
      {/* Post-promotion */}
      {pm && !pm.error && (
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 font-medium">Promo:</span>
          <span className="text-slate-600">day {pmDay}/30</span>
          {pmAlerts > 0 ? (
            <span className="bg-rose-100 text-rose-700 px-1 py-0.5 rounded font-semibold">{pmAlerts} alert{pmAlerts > 1 ? 's' : ''}</span>
          ) : (
            <span className="bg-emerald-100 text-emerald-700 px-1 py-0.5 rounded">OK</span>
          )}
        </div>
      )}

      <span className="text-slate-200">|</span>

      {/* Coinvest shadow */}
      {cs && !cs.error && (
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 font-medium">Coinvest:</span>
          <span className="text-slate-600">day {csDay}/30</span>
          {csOverlap != null && (
            <span className="text-indigo-600 font-semibold">{csOverlap}% overlap</span>
          )}
        </div>
      )}

      <span className="text-slate-200">|</span>

      {/* Regime */}
      {rs && !rs.error && (
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 font-medium">Regime:</span>
          {simpleRegime && (
            <span className={`font-semibold px-1 py-0.5 rounded ${
              simpleRegime.toUpperCase().includes('BEAR') ? 'bg-rose-100 text-rose-700'
              : simpleRegime.toUpperCase().includes('BULL') ? 'bg-emerald-100 text-emerald-700'
              : 'bg-amber-100 text-amber-700'
            }`}>{simpleRegime}</span>
          )}
          {richRegime && simpleRegime !== richRegime && (
            <>
              <span className="text-slate-300">/</span>
              <span className={`font-semibold px-1 py-0.5 rounded ${
                richRegime.toUpperCase().includes('BEAR') ? 'bg-rose-100 text-rose-700'
                : richRegime.toUpperCase().includes('BULL') ? 'bg-emerald-100 text-emerald-700'
                : 'bg-amber-100 text-amber-700'
              }`}>{richRegime}</span>
            </>
          )}
          <span className={agree ? 'text-emerald-600' : 'text-amber-600'}>
            {agree ? 'agree' : 'disagree'}
          </span>
        </div>
      )}
    </div>
  );
}
