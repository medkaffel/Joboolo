import React from 'react';
import AlertInlineBlock from './AlertInlineBlock';
import { MapPin, Search } from 'lucide-react';

const NEARBY_CITIES = ['Paris', 'Lyon', 'Marseille', 'Toulouse', 'Bordeaux', 'Lille', 'Nantes'];

const AdSlot = ({ label, testId }) => (
  <div
    className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 h-56 flex flex-col items-center justify-center text-slate-300 text-xs"
    data-testid={testId}
  >
    {/* AdSense slot — insert ca-pub-XXXX ins tag here */}
    <span className="uppercase tracking-widest">Publicité</span>
    <span className="mt-1 text-slate-300">{label}</span>
  </div>
);

// searchQuery: { job, location }; onRun: (query) => void
const ResultsSidebar = ({ searchQuery = {}, resultCount = null, onRun }) => {
  const job = searchQuery.job || '';
  const location = searchQuery.location || '';

  const similar = job
    ? [`${job} junior`, `${job} senior`, `${job} confirmé`, `${job} télétravail`]
    : [];
  const nearby = location
    ? NEARBY_CITIES.filter((c) => c.toLowerCase() !== location.toLowerCase()).slice(0, 5)
    : [];

  return (
    <aside className="space-y-5" data-testid="results-sidebar">
      <AdSlot label="300 × 250" testId="adsense-placeholder-top" />

      <AlertInlineBlock searchQuery={searchQuery} variant="compact" resultCount={resultCount} />

      {similar.length > 0 && (
        <div className="rounded-2xl border border-slate-100 bg-white p-4" data-testid="similar-searches">
          <h3 className="font-heading text-sm font-semibold text-slate-900 mb-3">Recherches similaires</h3>
          <ul className="space-y-1.5">
            {similar.map((s, i) => (
              <li key={i}>
                <button
                  onClick={() => onRun({ job: s, location })}
                  className="flex items-center gap-2 text-sm text-slate-600 hover:text-brand transition-colors w-full text-left"
                  data-testid={`similar-search-${i}`}
                >
                  <Search className="h-3.5 w-3.5 shrink-0" /> {s}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {nearby.length > 0 && (
        <div className="rounded-2xl border border-slate-100 bg-white p-4" data-testid="nearby-searches">
          <h3 className="font-heading text-sm font-semibold text-slate-900 mb-3">Recherche à proximité de {location}</h3>
          <ul className="space-y-1.5">
            {nearby.map((c, i) => (
              <li key={i}>
                <button
                  onClick={() => onRun({ job, location: c })}
                  className="flex items-center gap-2 text-sm text-slate-600 hover:text-brand transition-colors w-full text-left"
                  data-testid={`nearby-search-${i}`}
                >
                  <MapPin className="h-3.5 w-3.5 shrink-0" /> {job || 'Emplois'} à {c}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <AdSlot label="300 × 250" testId="adsense-placeholder-bottom" />
    </aside>
  );
};

export default ResultsSidebar;
