import { useEffect, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { fetchShadowPerformance } from './api';

export default function ShadowPnLStrip() {
  const [data, setData] = useState<any[]>([]);

  useEffect(() => {
    fetchShadowPerformance().then((d) => {
      if (Array.isArray(d) && d.length > 0) {
        // Compute cumulative returns
        let cum = 0;
        let cumXbi = 0;
        const series = d.map((r: any) => {
          cum += parseFloat(r.pnl_pct || 0);
          cumXbi += parseFloat(r.xbi_pct || 0);
          return {
            date: r.date,
            dem: parseFloat(cum.toFixed(2)),
            xbi: parseFloat(cumXbi.toFixed(2)),
            excess: parseFloat((cum - cumXbi).toFixed(2)),
          };
        });
        setData(series);
      }
    });
  }, []);

  if (data.length === 0) return null;

  const latest = data[data.length - 1];

  return (
    <div className="rounded-lg border p-3 mb-3">
      <div className="flex justify-between items-center mb-2">
        <div className="text-xs font-medium">Shadow vs XBI</div>
        <div className="flex gap-3 text-[10px]">
          <span className="text-indigo-600 font-semibold">DEM {latest.dem > 0 ? '+' : ''}{latest.dem}%</span>
          <span className="text-slate-400">XBI {latest.xbi > 0 ? '+' : ''}{latest.xbi}%</span>
          <span className={`font-semibold ${latest.excess >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
            Excess {latest.excess > 0 ? '+' : ''}{latest.excess}%
          </span>
        </div>
      </div>
      <div className="h-24">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ left: 0, right: 5, top: 2, bottom: 2 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="date" tick={{ fontSize: 8 }} interval={Math.floor(data.length / 5)} />
            <YAxis tick={{ fontSize: 9 }} tickFormatter={(v) => `${v}%`} width={35} />
            <Tooltip
              contentStyle={{ fontSize: 11, borderRadius: 8, border: '0.5px solid #e2e8f0' }}
              formatter={(v: any, name: any) => [`${v}%`, name === 'dem' ? 'DEM' : name === 'xbi' ? 'XBI' : 'Excess']}
            />
            <Line type="monotone" dataKey="dem" stroke="#6366f1" strokeWidth={2} dot={false} name="dem" />
            <Line type="monotone" dataKey="xbi" stroke="#94a3b8" strokeWidth={1.5} dot={false} strokeDasharray="4 4" name="xbi" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
