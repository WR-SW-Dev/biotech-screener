interface Props {
  rows: any[];
  onSelectTicker: (ticker: string) => void;
}

function n(v: any): number { const x = parseFloat(v); return isNaN(x) ? 0 : x; }

export default function RankChangeStrip({ rows, onSelectTicker }: Props) {
  // Filter to names with rank_prior data and significant movement
  const movers = rows
    .filter(r => {
      const rank = n(r.actionable_rank);
      const prior = n(r.rank_prior || r.actionable_rank);
      return rank > 0 && prior > 0 && Math.abs(rank - prior) >= 3;
    })
    .map(r => ({
      ticker: r.ticker,
      rank: n(r.actionable_rank),
      prior: n(r.rank_prior || r.actionable_rank),
      delta: n(r.rank_prior || r.actionable_rank) - n(r.actionable_rank), // positive = improved
      tier: r.tier_any,
    }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 12);

  if (movers.length === 0) return null;

  const maxDelta = Math.max(...movers.map(m => Math.abs(m.delta)), 1);

  return (
    <div className="rounded-lg border p-3 mb-3">
      <div className="text-xs font-medium mb-2">Rank changes vs prior snapshot</div>
      <div className="space-y-1">
        {movers.map(m => {
          const pct = Math.abs(m.delta) / maxDelta;
          const isUp = m.delta > 0;
          return (
            <button
              key={m.ticker}
              onClick={() => onSelectTicker(m.ticker)}
              className="flex items-center gap-2 w-full text-left hover:bg-slate-50 rounded px-1 py-0.5 transition"
            >
              <span className="text-[10px] font-semibold w-10 text-indigo-600">{m.ticker}</span>
              <span className="text-[10px] text-slate-400 w-6">#{m.rank}</span>
              <div className="flex-1 h-3 relative">
                <div className="absolute inset-0 bg-slate-100 rounded" />
                <div
                  className="absolute top-0 h-3 rounded"
                  style={{
                    width: `${pct * 100}%`,
                    background: isUp ? '#22c55e' : '#ef4444',
                    opacity: 0.6,
                    left: isUp ? '50%' : `${50 - pct * 50}%`,
                    maxWidth: '50%',
                  }}
                />
                <div className="absolute inset-y-0 left-1/2 w-px bg-slate-300" />
              </div>
              <span className={`text-[10px] font-semibold w-8 text-right ${isUp ? 'text-emerald-600' : 'text-rose-600'}`}>
                {isUp ? '+' : ''}{m.delta}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
