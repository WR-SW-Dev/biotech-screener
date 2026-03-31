import { useState, useMemo } from 'react';
import { Search, Filter } from 'lucide-react';

interface RankingRow {
  ticker: string;
  actionable_rank: string;
  tier_any: string;
  catalyst_days: string;
  catalyst_family: string;
  is_hard_catalyst: string;
  clinical_optionality_pct_dev: string;
  mom_state: string;
  archetype: string;
  [key: string]: string;
}

interface Props {
  rows: RankingRow[];
  onSelectTicker: (ticker: string) => void;
  selectedTicker: string;
}

const tierColor: Record<string, string> = {
  A: 'bg-emerald-100 text-emerald-800',
  B: 'bg-amber-100 text-amber-800',
  C: 'bg-slate-100 text-slate-700',
  D: 'bg-slate-50 text-slate-500',
};

export default function RankingsTable({ rows, onSelectTicker, selectedTicker }: Props) {
  const [query, setQuery] = useState('');
  const [tierFilter, setTierFilter] = useState('all');
  const [familyFilter, setFamilyFilter] = useState('all');
  const [hardOnly, setHardOnly] = useState(false);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      const q = query.toLowerCase();
      const matchQ = !q || r.ticker.toLowerCase().includes(q) || (r.archetype || '').toLowerCase().includes(q);
      const matchTier = tierFilter === 'all' || r.tier_any === tierFilter;
      const matchFam = familyFilter === 'all' || r.catalyst_family === familyFilter;
      const matchHard = !hardOnly || r.is_hard_catalyst === '1';
      return matchQ && matchTier && matchFam && matchHard;
    });
  }, [rows, query, tierFilter, familyFilter, hardOnly]);

  // Group by tier
  const tierGroups = useMemo(() => {
    const groups: Record<string, RankingRow[]> = { A: [], B: [], C: [], D: [], other: [] };
    for (const r of filtered) {
      const t = r.tier_any || 'other';
      (groups[t] || groups.other).push(r);
    }
    return groups;
  }, [filtered]);

  const pct = (v: string) => {
    const n = parseFloat(v);
    return isNaN(n) ? '—' : `${(n * 100).toFixed(0)}%`;
  };

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 p-4 border-b border-slate-200 bg-white sticky top-0 z-10">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search ticker..."
            className="pl-9 pr-3 py-2 text-sm border rounded-lg w-48 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>
        <select value={tierFilter} onChange={(e) => setTierFilter(e.target.value)} className="text-sm border rounded-lg px-3 py-2">
          <option value="all">All tiers</option>
          <option value="A">Tier A</option>
          <option value="B">Tier B</option>
          <option value="C">Tier C</option>
        </select>
        <select value={familyFilter} onChange={(e) => setFamilyFilter(e.target.value)} className="text-sm border rounded-lg px-3 py-2">
          <option value="all">All families</option>
          <option value="CLINICAL">Clinical</option>
          <option value="REGULATORY">Regulatory</option>
        </select>
        <button
          onClick={() => setHardOnly(!hardOnly)}
          className={`flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border ${hardOnly ? 'bg-emerald-50 border-emerald-300 text-emerald-700' : 'text-slate-600'}`}
        >
          <Filter className="h-3.5 w-3.5" />
          Hard only
        </button>
        <span className="ml-auto text-xs text-slate-400">{filtered.length} names</span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {(['A', 'B', 'C', 'D'] as const).map((tier) => {
          const group = tierGroups[tier];
          if (!group?.length) return null;
          return (
            <div key={tier}>
              <div className="sticky top-0 bg-slate-50 px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500 border-b">
                Tier {tier} — {group.length} names
              </div>
              {group.map((r) => (
                <button
                  key={r.ticker}
                  onClick={() => onSelectTicker(r.ticker)}
                  className={`w-full grid grid-cols-[3rem_5rem_4rem_5rem_3.5rem_5rem_4rem] gap-3 px-4 py-2.5 text-left text-sm border-b hover:bg-slate-50 transition ${
                    selectedTicker === r.ticker ? 'bg-emerald-50' : 'bg-white'
                  }`}
                >
                  <span className="font-mono text-slate-500">#{r.actionable_rank}</span>
                  <span className="font-semibold">{r.ticker}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded text-center ${tierColor[r.tier_any] || tierColor.D}`}>
                    {r.tier_any}
                  </span>
                  <span className="text-slate-600">{r.catalyst_days}d</span>
                  <span>{r.is_hard_catalyst === '1' ? '🎯' : '○'}</span>
                  <span className="text-slate-600">{pct(r.clinical_optionality_pct_dev)}</span>
                  <span className={`text-xs ${r.mom_state === 'tailwind' ? 'text-emerald-600' : r.mom_state === 'headwind' ? 'text-rose-600' : 'text-slate-500'}`}>
                    {r.mom_state || '—'}
                  </span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
