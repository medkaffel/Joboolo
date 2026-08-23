import React, { useState, useEffect } from 'react';
import JobCard from './JobCard';
import { jobService } from '../services/jobService';
import { Button } from './ui/button';
import { Separator } from './ui/separator';
import { Loader2, SlidersHorizontal, Sparkles } from 'lucide-react';
import AlertInlineBlock from './AlertInlineBlock';
import ResultsSidebar from './ResultsSidebar';

const CONTRACT_TYPES = ['CDI', 'CDD', 'Stage', 'Freelance', 'Intérim', 'Titulaire'];
const DATE_OPTIONS = [
  { value: '', label: 'Toutes dates' },
  { value: '1', label: "Aujourd'hui" },
  { value: '3', label: '3 derniers jours' },
  { value: '7', label: '7 derniers jours' },
  { value: '30', label: '30 derniers jours' },
];

const JobList = ({ jobs, searchQuery, loading, pagination, filters = {}, onFilterChange, onPageChange, onRunSearch }) => {
  const hasSearch = searchQuery.job || searchQuery.location;
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Vraies impressions : log les offres partenaires affichées (dédupliquées par session)
  useEffect(() => {
    const partnerIds = (jobs || []).filter((j) => j.is_partner).map((j) => j.id);
    if (!partnerIds.length) return;
    let seen = [];
    try { seen = JSON.parse(sessionStorage.getItem('joboolo_impr') || '[]'); } catch { seen = []; }
    const fresh = partnerIds.filter((id) => !seen.includes(id));
    if (!fresh.length) return;
    jobService.recordImpressions(fresh);
    sessionStorage.setItem('joboolo_impr', JSON.stringify([...seen, ...fresh].slice(-1000)));
  }, [jobs]);

  const setFilter = (patch) => onFilterChange && onFilterChange({ ...filters, ...patch });

  const pageNumbers = () => {
    if (!pagination) return [];
    const total = pagination.totalPages;
    const cur = pagination.page;
    const pages = [];
    const from = Math.max(1, cur - 2);
    const to = Math.min(total, cur + 2);
    for (let i = from; i <= to; i++) pages.push(i);
    return pages;
  };

  if (loading && jobs.length === 0) {
    return (
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex justify-center items-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-brand" />
          <span className="ml-2 text-gray-600">Chargement des offres...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="job-list-section">
      {/* Header */}
      <div className="mb-6">
        <h2 className="font-heading text-3xl font-bold tracking-tight text-slate-900 mb-2">
          {hasSearch ? 'Résultats de recherche' : 'Emplois recommandés'}
        </h2>
        <p className="text-slate-500">
          {hasSearch ? (
            <>
              {searchQuery.job && <>Emplois "{searchQuery.job}"</>}
              {searchQuery.job && searchQuery.location && ' à '}
              {searchQuery.location && <>{searchQuery.location}</>}
            </>
          ) : "Découvrez les dernières offres d'emploi"}
        </p>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <select
          value={filters.job_type || ''}
          onChange={(e) => setFilter({ job_type: e.target.value })}
          className="text-sm border border-slate-200 rounded-full px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-brand/30 text-slate-600"
          data-testid="filter-contract-type"
        >
          <option value="">Type de contrat</option>
          {CONTRACT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <select
          value={filters.posted_within || ''}
          onChange={(e) => setFilter({ posted_within: e.target.value })}
          className="text-sm border border-slate-200 rounded-full px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-brand/30 text-slate-600"
          data-testid="filter-date-posted"
        >
          {DATE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>

        <select
          value={filters.sort || 'created_at'}
          onChange={(e) => setFilter({ sort: e.target.value })}
          className="text-sm border border-slate-200 rounded-full px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-brand/30 text-slate-600"
          data-testid="filter-sort"
        >
          <option value="created_at">Trier par date</option>
          <option value="salary_min">Trier par salaire</option>
          <option value="title">Trier par titre</option>
        </select>

        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand hover:text-brand-hover transition-colors ml-auto"
          data-testid="advanced-search-toggle"
        >
          <SlidersHorizontal className="h-4 w-4" />
          Recherche avancée
          <Sparkles className="h-4 w-4 text-amber-400" />
        </button>
      </div>

      {/* Advanced panel */}
      {showAdvanced && (
        <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4 mb-4 grid sm:grid-cols-3 gap-3 animate-fade-up" data-testid="advanced-search-panel">
          <input
            type="text"
            placeholder="Entreprise"
            value={filters.company || ''}
            onChange={(e) => setFilter({ company: e.target.value })}
            className="h-10 px-4 rounded-full border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
            data-testid="advanced-company"
          />
          <input
            type="number"
            placeholder="Salaire min (€)"
            value={filters.salary_min || ''}
            onChange={(e) => setFilter({ salary_min: e.target.value })}
            className="h-10 px-4 rounded-full border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
            data-testid="advanced-salary"
          />
          <label className="flex items-center gap-2 text-sm text-slate-600 px-2">
            <input
              type="checkbox"
              checked={!!filters.is_remote}
              onChange={(e) => setFilter({ is_remote: e.target.checked })}
              className="h-4 w-4 accent-brand"
              data-testid="advanced-remote"
            />
            Télétravail uniquement
          </label>
        </div>
      )}

      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-slate-500" data-testid="results-count">
          {pagination ? `${pagination.total} emplois trouvés` : `${jobs.length} emplois`}
        </span>
      </div>
      <Separator className="mb-6" />

      {/* Two-column layout */}
      <div className={hasSearch ? 'grid lg:grid-cols-[1fr_320px] gap-8' : ''}>
        <div>
          {/* Alert subscribe block — always shown so users can subscribe even with 0 results */}
          <div className="mb-4">
            <AlertInlineBlock searchQuery={searchQuery} variant="banner" resultCount={pagination?.total} />
          </div>

          {jobs.length > 0 ? (
            <>
              <div className="space-y-4 mb-8">
                {jobs.map((job, idx) => (
                  <React.Fragment key={job.id}>
                    <JobCard job={job} />
                    {/* Middle alert block if more than 10 jobs on the page */}
                    {jobs.length > 10 && idx === Math.floor(jobs.length / 2) && (
                      <div className="my-4">
                        <AlertInlineBlock searchQuery={searchQuery} variant="banner" resultCount={pagination?.total} />
                      </div>
                    )}
                  </React.Fragment>
                ))}
              </div>

              {/* Numbered pagination */}
              {pagination && pagination.totalPages > 1 && (
                <div className="flex items-center justify-center gap-1.5 flex-wrap" data-testid="pagination">
                  <Button
                    variant="outline" size="sm" className="rounded-full"
                    disabled={pagination.page <= 1}
                    onClick={() => onPageChange(pagination.page - 1)}
                    data-testid="pagination-prev"
                  >Précédent</Button>
                  {pageNumbers()[0] > 1 && <span className="px-2 text-slate-400">…</span>}
                  {pageNumbers().map((p) => (
                    <Button
                      key={p}
                      variant={p === pagination.page ? 'default' : 'outline'}
                      size="sm"
                      className={`rounded-full w-9 ${p === pagination.page ? 'bg-brand hover:bg-brand-hover' : ''}`}
                      onClick={() => onPageChange(p)}
                      data-testid={`pagination-page-${p}`}
                    >{p}</Button>
                  ))}
                  {pageNumbers()[pageNumbers().length - 1] < pagination.totalPages && <span className="px-2 text-slate-400">…</span>}
                  <Button
                    variant="outline" size="sm" className="rounded-full"
                    disabled={pagination.page >= pagination.totalPages}
                    onClick={() => onPageChange(pagination.page + 1)}
                    data-testid="pagination-next"
                  >Suivant</Button>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-12">
              <div className="text-gray-500 text-lg mb-2">Aucune offre trouvée</div>
              <p className="text-gray-400">Essayez de modifier vos critères de recherche.</p>
            </div>
          )}
        </div>

        {hasSearch && (
          <ResultsSidebar
            searchQuery={searchQuery}
            resultCount={pagination?.total}
            onRun={(q) => onRunSearch && onRunSearch(q)}
          />
        )}
      </div>
    </div>
  );
};

export default JobList;
