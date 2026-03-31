import { useEffect, useState } from 'react';
import { fetchTierBucketHeatmap } from './api';

interface Props { date: string; }

const tierLabel: Record<string, string> = { A: 'Tier A', B: 'Tier B', C: 'Tier C', D: 'Tier D' };

function cellColor(count: number, max: number): string {
  if (count === 0) return '#f8fafc';
  const t = Math.min(1, count / Math.max(max, 1));
  const r = Math.round(240 - t * 200);
  const g = Math.round(250 - t * 100);
  const b = Math.round(255 - t * 50);
  return `rgb(${r},${g},${b})`;
}

export default function TierBucketHeatmap({ date }: Props) {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    if (date) fetchTierBucketHeatmap(date).then(setData);
  }, [date]);

  if (!data || data.error) return null;

  const { tiers, buckets, counts } = data;
  const max = Math.max(...Object.values(counts).map(Number));

  return (
    <div className="rounded-lg border p-3 mb-3">
      <div className="text-xs font-medium mb-2">Tier × Bucket deployment</div>
      <div className="overflow-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr>
              <th className="text-left p-1 text-slate-400"></th>
              {buckets.map((b: string) => (
                <th key={b} className="text-center p-1 text-slate-400 font-medium">{b.replace('_', ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tiers.map((t: string) => (
              <tr key={t}>
                <td className="p-1 font-semibold text-slate-600">{tierLabel[t] || t}</td>
                {buckets.map((b: string) => {
                  const count = counts[`${t}|${b}`] || 0;
                  return (
                    <td key={b} className="text-center p-1">
                      <div
                        className="rounded px-2 py-1 font-semibold mx-auto w-10"
                        style={{ background: cellColor(count, max), color: count > max * 0.5 ? '#1e293b' : '#94a3b8' }}
                      >
                        {count}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
