import React, { useState, useEffect } from 'react';
import { Button } from './ui/button';
import { Search, MapPin, AlertCircle, Briefcase } from 'lucide-react';
import WelcomeMessage from './WelcomeMessage';
import AutocompleteInput from './AutocompleteInput';

const POPULAR = [
  'Développeur web', 'Marketing digital', 'Commercial',
  'Infirmier', 'Comptable', 'Chargé de communication',
];

const RADIUS_OPTIONS = [
  { value: '', label: 'Distance' },
  { value: '5', label: '5 km' },
  { value: '10', label: '10 km' },
  { value: '25', label: '25 km' },
  { value: '50', label: '50 km' },
  { value: '100', label: '100 km' },
];

const SearchSection = ({ onSearch, initialQuery, hidePopular = false }) => {
  const [jobQuery, setJobQuery] = useState(initialQuery?.job || '');
  const [locationQuery, setLocationQuery] = useState(initialQuery?.location || '');
  const [radius, setRadius] = useState('');
  const [warning, setWarning] = useState('');

  // Sync location prefilled by parent (e.g. IP geo-detection)
  useEffect(() => {
    if (initialQuery?.location) setLocationQuery(initialQuery.location);
  }, [initialQuery?.location]);

  const handleSearch = (e) => {
    if (e) e.preventDefault();
    if (!jobQuery.trim() && !locationQuery.trim()) {
      setWarning('Veuillez renseigner un métier/mot-clé ou une localisation pour lancer la recherche.');
      return;
    }
    setWarning('');
    onSearch({ job: jobQuery, location: locationQuery, radius });
  };

  return (
    <section className="relative overflow-hidden bg-slate-50">
      {/* Soft radial accents */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-24 -right-24 h-96 w-96 rounded-full bg-brand/10 blur-3xl" />
        <div className="absolute top-40 -left-24 h-72 w-72 rounded-full bg-emerald-200/30 blur-3xl" />
      </div>

      <div className="relative max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-20 sm:py-28">
        <div className="animate-fade-up">
          <WelcomeMessage />
        </div>

        <div className="text-center mb-10 animate-fade-up" style={{ animationDelay: '80ms' }}>
          <h1 className="font-heading text-2xl sm:text-2xl lg:text-3xl font-extrabold tracking-tight text-slate-900 leading-[1.1]">
            Trouvez le poste<br className="hidden sm:block" /> qui vous <span className="text-brand">correspond</span>
          </h1>
          <p className="mt-4 text-sm md:text-base text-slate-500 max-w-2xl mx-auto">
            Des milliers d'offres d'emploi en France, mises à jour chaque jour.
          </p>
        </div>

        {/* Floating pill search bar */}
        <form onSubmit={handleSearch} className="animate-fade-up" style={{ animationDelay: '160ms' }}>
          <div className="flex flex-col md:flex-row items-stretch gap-2 md:gap-0 bg-white rounded-3xl md:rounded-full p-2 shadow-[0_8px_30px_rgb(0,0,0,0.08)] border border-slate-100">
            <AutocompleteInput
              value={jobQuery}
              onChange={setJobQuery}
              field="title"
              icon={Briefcase}
              placeholder="Quoi ? Métier, mot-clé ou entreprise"
              testId="search-job-input"
            />

            <div className="hidden md:block w-px bg-slate-200 my-2" />

            <AutocompleteInput
              value={locationQuery}
              onChange={setLocationQuery}
              field="location"
              icon={MapPin}
              placeholder="Où ? Ville ou code postal"
              testId="search-location-input"
            />

            <div className="hidden md:block w-px bg-slate-200 my-2" />

            <div className="flex items-center px-2">
              <select
                value={radius}
                onChange={(e) => setRadius(e.target.value)}
                className="h-12 md:h-14 bg-transparent text-sm text-slate-600 focus:outline-none rounded-full px-2"
                data-testid="search-radius-select"
                aria-label="Rayon de distance"
              >
                {RADIUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            <Button
              type="submit"
              className="h-12 md:h-14 px-8 rounded-full bg-brand hover:bg-brand-hover text-white font-semibold text-base transition-transform active:scale-95"
              data-testid="search-submit-btn"
            >
              <Search className="h-5 w-5 mr-2" />
              Rechercher
            </Button>
          </div>
          {warning && (
            <div className="flex items-center justify-center gap-2 mt-3 text-sm text-red-500 animate-fade-up" data-testid="search-warning">
              <AlertCircle className="h-4 w-4" />{warning}
            </div>
          )}
        </form>

        {/* Popular searches (hidden for returning visitors with history) */}
        {!hidePopular && (
          <div className="text-center mt-10 animate-fade-up" style={{ animationDelay: '280ms' }}>
            <p className="text-sm text-slate-400 mb-3 uppercase tracking-widest">Recherches populaires</p>
            <div className="flex flex-wrap justify-center gap-2">
              {POPULAR.map((s) => (
                <button
                  key={s}
                  onClick={() => { setJobQuery(s); onSearch({ job: s, location: locationQuery, radius }); }}
                  className="px-4 py-2 text-sm rounded-full bg-white border border-slate-200 text-slate-600 hover:border-brand hover:text-brand transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
};

export default SearchSection;
