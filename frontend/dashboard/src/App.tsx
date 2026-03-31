import { useEffect, useState } from 'react';
import RankingsTable from './RankingsTable';
import TickerDetail from './TickerDetail';
import BioshortPanel from './BioshortPanel';
import CRTCalibration from './CRTCalibration';
import { fetchDates, fetchRankings } from './api';
import './index.css';

type View = 'screener' | 'bioshort' | 'calibration';

export default function App() {
  const [view, setView] = useState<View>('screener');
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState('');
  const [rows, setRows] = useState<any[]>([]);
  const [selectedTicker, setSelectedTicker] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDates().then((d) => {
      setDates(d);
      if (d.length > 0) setSelectedDate(d[0]);
    });
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    fetchRankings(selectedDate, 100).then((r) => {
      setRows(r);
      if (r.length > 0 && !selectedTicker) {
        setSelectedTicker(r[0].ticker);
      }
      setLoading(false);
    });
  }, [selectedDate]);

  const tabs: { key: View; label: string }[] = [
    { key: 'screener', label: 'Screener' },
    { key: 'bioshort', label: 'Bioshort' },
    { key: 'calibration', label: 'Calibration' },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <div>
            <div className="text-xs font-medium uppercase tracking-widest text-slate-400">Wake Robin</div>
            <h1 className="text-lg font-semibold">Biotech Screener</h1>
          </div>
          <nav className="flex gap-1 bg-slate-100 rounded-lg p-0.5">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setView(t.key)}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition ${
                  view === t.key ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="text-sm border rounded-lg px-3 py-1.5"
          >
            {dates.slice(0, 30).map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <span className="text-xs text-slate-400">{rows.length} names</span>
        </div>
      </header>

      {view === 'screener' && (
        loading ? (
          <div className="flex items-center justify-center h-96 text-slate-400">Loading...</div>
        ) : (
          <div className="grid grid-cols-[minmax(520px,1fr)_minmax(380px,0.7fr)] h-[calc(100vh-57px)]">
            <div className="border-r overflow-hidden">
              <RankingsTable
                rows={rows}
                onSelectTicker={setSelectedTicker}
                selectedTicker={selectedTicker}
              />
            </div>
            <div className="overflow-hidden">
              <TickerDetail ticker={selectedTicker} date={selectedDate} />
            </div>
          </div>
        )
      )}

      {view === 'bioshort' && (
        <div className="max-w-3xl mx-auto py-6">
          <BioshortPanel />
        </div>
      )}

      {view === 'calibration' && (
        <CRTCalibration />
      )}
    </div>
  );
}
