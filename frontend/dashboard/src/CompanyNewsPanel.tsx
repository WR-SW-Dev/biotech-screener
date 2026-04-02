import { useEffect, useState } from 'react';
import { fetchHeraldHealth, fetchHeraldReleases, fetchHeraldClassified } from './api';

interface Props { date: string; }

function Stat({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="text-[10px] text-slate-400 uppercase tracking-wide">{label}</div>
      <div className="text-lg font-semibold mt-0.5" style={accent ? { color: accent } : {}}>{value}</div>
    </div>
  );
}

const CAT_COLORS: Record<string, string> = {
  clinical: 'bg-emerald-100 text-emerald-800',
  regulatory: 'bg-blue-100 text-blue-800',
  mna: 'bg-violet-100 text-violet-800',
  financing: 'bg-amber-100 text-amber-800',
  safety: 'bg-rose-100 text-rose-800',
  other: 'bg-slate-100 text-slate-600',
};

export default function CompanyNewsPanel({ date }: Props) {
  const [health, setHealth] = useState<any>(null);
  const [releases, setReleases] = useState<any[]>([]);
  const [classified, setClassified] = useState<any[]>([]);
  const [tab, setTab] = useState<'releases' | 'classified' | 'health'>('releases');
  const [catFilter, setCatFilter] = useState<string>('all');
  const [hideInfo, setHideInfo] = useState(true);

  useEffect(() => {
    fetchHeraldHealth().then(setHealth);
    if (date) {
      fetchHeraldReleases(date).then(setReleases);
      fetchHeraldClassified(date).then(setClassified);
    }
  }, [date]);

  const h = health || {};
  const hasData = !h.error;

  return (
    <div className="p-6 space-y-4 max-w-5xl mx-auto">
      <h2 className="text-xl font-semibold">Company News (Herald)</h2>

      {/* Health stats */}
      {hasData && (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-2">
          <Stat label="Tickers" value={h.tickers_attempted || 0} />
          <Stat label="Sources OK" value={h.sources_succeeded || 0} accent="#22c55e" />
          <Stat label="Failed" value={h.sources_failed || 0} accent={h.sources_failed > 0 ? '#ef4444' : undefined} />
          <Stat label="New PRs" value={h.new_releases || 0} accent="#6366f1" />
          <Stat label="Direct IR" value={h.direct_ir_hits || 0} />
          <Stat label="Backup" value={h.backup_hits || 0} />
        </div>
      )}

      {!hasData && (
        <div className="rounded-lg border border-dashed p-6 text-slate-400 text-center text-sm">
          No Herald data yet. Herald runs daily at 3:00 PM ET before the production pipeline.
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b text-sm">
        {(['releases', 'classified', 'health'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 font-medium capitalize ${tab === t ? 'border-b-2 border-indigo-600 text-indigo-700' : 'text-slate-400'}`}>
            {t} {t === 'releases' ? `(${releases.length})` : t === 'classified' ? `(${classified.length})` : ''}
          </button>
        ))}
      </div>

      {/* Releases */}
      {tab === 'releases' && (
        releases.length === 0 ? (
          <div className="text-sm text-slate-400 text-center p-4">No releases for {date}</div>
        ) : (
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Ticker</th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Headline</th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Source</th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Date</th>
                </tr>
              </thead>
              <tbody>
                {releases.map((r, i) => (
                  <tr key={i} className="border-t hover:bg-slate-50">
                    <td className="px-3 py-2 font-semibold text-indigo-600">{r.ticker}</td>
                    <td className="px-3 py-2 text-slate-700 max-w-md truncate">{r.headline}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{r.source_type}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{r.published_at_utc || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Classified */}
      {tab === 'classified' && (() => {
        const cats = classified.reduce((acc, r) => { acc[r.event_category] = (acc[r.event_category] || 0) + 1; return acc; }, {} as Record<string, number>);
        const filtered = classified.filter(r => {
          if (hideInfo && r.informational_only) return false;
          if (catFilter !== 'all' && r.event_category !== catFilter) return false;
          return true;
        });
        const materialCount = classified.filter(r => !r.informational_only && r.event_category !== 'other').length;

        return classified.length === 0 ? (
          <div className="text-sm text-slate-400 text-center p-4">No classified releases for {date}</div>
        ) : (
          <div className="space-y-2">
            {/* Category summary */}
            <div className="flex items-center gap-2 flex-wrap">
              <button onClick={() => setCatFilter('all')}
                className={`text-xs px-2 py-1 rounded font-medium ${catFilter === 'all' ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                All ({classified.length})
              </button>
              {Object.entries(cats).sort((a, b) => b[1] - a[1]).map(([cat, n]) => (
                <button key={cat} onClick={() => setCatFilter(catFilter === cat ? 'all' : cat)}
                  className={`text-xs px-2 py-1 rounded font-medium ${catFilter === cat ? 'ring-2 ring-indigo-400 ' : ''}${CAT_COLORS[cat] || CAT_COLORS.other}`}>
                  {cat} ({n})
                </button>
              ))}
              <label className="ml-auto flex items-center gap-1.5 text-xs text-slate-500 cursor-pointer select-none">
                <input type="checkbox" checked={hideInfo} onChange={() => setHideInfo(!hideInfo)} className="rounded" />
                Hide informational
              </label>
            </div>
            <div className="text-xs text-slate-400">
              Material events: {materialCount} | Showing: {filtered.length}
            </div>

            <div className="rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Ticker</th>
                    <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Headline</th>
                    <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Category</th>
                    <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">Severity</th>
                    <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">Conf</th>
                    <th className="text-center px-3 py-2 text-xs font-medium text-slate-500">Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r, i) => (
                    <tr key={i} className="border-t hover:bg-slate-50">
                      <td className="px-3 py-2 font-semibold text-indigo-600">{r.ticker}</td>
                      <td className="px-3 py-2 text-slate-700 max-w-md truncate" title={r.headline}>{r.headline}</td>
                      <td className="px-3 py-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${CAT_COLORS[r.event_category] || CAT_COLORS.other}`}>
                          {r.event_category}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          r.severity === 'critical' ? 'bg-rose-100 text-rose-800' :
                          r.severity === 'high' ? 'bg-amber-100 text-amber-800' :
                          'bg-slate-100 text-slate-600'
                        }`}>{r.severity}</span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">{typeof r.confidence === 'number' ? r.confidence.toFixed(1) : '\u2014'}</td>
                      <td className="px-3 py-1.5 text-center space-x-0.5">
                        {r.mna_signal_flag && <span className="text-[10px] bg-violet-100 text-violet-700 px-1 rounded">M&A</span>}
                        {r.financing_signal_flag && <span className="text-[10px] bg-amber-100 text-amber-700 px-1 rounded">$</span>}
                        {r.safety_signal_flag && <span className="text-[10px] bg-rose-100 text-rose-700 px-1 rounded">SAFETY</span>}
                        {r.thesis_change_flag && !r.mna_signal_flag && !r.safety_signal_flag && <span className="text-[10px] bg-indigo-100 text-indigo-700 px-1 rounded">THESIS</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {/* Health detail */}
      {tab === 'health' && hasData && (
        <div className="space-y-3">
          <div className="rounded-lg bg-slate-50 p-3 text-sm">
            <span className="font-medium">Last run:</span> {h.generated_at || '—'}
          </div>
          {h.failures && h.failures.length > 0 && (
            <div>
              <div className="text-xs font-medium text-slate-500 mb-1">Fetch failures ({h.failures.length})</div>
              <div className="space-y-1">
                {h.failures.map((f: any, i: number) => (
                  <div key={i} className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800">
                    {f.ticker} — {f.source_type} — {f.error}
                  </div>
                ))}
              </div>
            </div>
          )}
          {(!h.failures || h.failures.length === 0) && (
            <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              All sources succeeded — no failures.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
