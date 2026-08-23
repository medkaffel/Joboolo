import React, { useState, useEffect } from 'react';
import { History, Bell, Trash2, Search } from 'lucide-react';
import { getHistory, removeSearch, clearHistory } from '../utils/searchHistory';

// onRun: (search) => void  |  onCreateAlert: (search) => void
const RecentSearches = ({ onRun, onCreateAlert }) => {
  const [list, setList] = useState([]);

  useEffect(() => {
    const refresh = () => setList(getHistory());
    refresh();
    window.addEventListener('joboolo-history-changed', refresh);
    return () => window.removeEventListener('joboolo-history-changed', refresh);
  }, []);

  if (!list.length) return null;

  const label = (s) => [s.job, s.location].filter(Boolean).join(' · ') || 'Toutes les offres';

  return (
    <section className="bg-slate-50 py-8 border-t border-slate-100" data-testid="recent-searches-section">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-heading text-lg font-semibold text-slate-900 flex items-center gap-2">
            <History className="h-5 w-5 text-brand" /> Mes dernières recherches
          </h2>
          <button
            onClick={() => clearHistory()}
            className="text-sm text-slate-400 hover:text-red-500 transition-colors"
            data-testid="clear-history-btn"
          >
            Tout effacer
          </button>
        </div>
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {list.map((s, i) => (
            <li
              key={i}
              className={`${i >= 3 ? 'hidden md:flex' : 'flex'} items-center justify-between bg-white rounded-xl border border-slate-100 px-4 py-3 hover:border-brand/40 transition-colors`}
              data-testid={`recent-search-${i}`}
            >
              <button onClick={() => onRun(s)} className="flex items-center gap-3 text-left flex-1 min-w-0">
                <Search className="h-4 w-4 text-slate-400 shrink-0" />
                <span className="text-sm text-slate-700 truncate">{label(s)}</span>
              </button>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => onCreateAlert(s)}
                  title="Transformer en alerte"
                  className="h-8 w-8 rounded-lg text-brand hover:bg-brand/10 flex items-center justify-center transition-colors"
                  data-testid={`recent-to-alert-${i}`}
                >
                  <Bell className="h-4 w-4" />
                </button>
                <button
                  onClick={() => removeSearch(i)}
                  title="Supprimer de l'historique"
                  className="h-8 w-8 rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-500 flex items-center justify-center transition-colors"
                  data-testid={`recent-remove-${i}`}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
};

export default RecentSearches;
