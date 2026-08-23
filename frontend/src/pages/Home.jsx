import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import Header from '../components/Header';
import SearchSection from '../components/SearchSection';
import JobList from '../components/JobList';
import Footer from '../components/Footer';
import WhyJoboolo from '../components/WhyJoboolo';
import RecentSearches from '../components/RecentSearches';
import BackToTop from '../components/BackToTop';
import AlertSlider from '../components/AlertSlider';
import { jobService } from '../services/jobService';
import { geoService } from '../services/geoService';
import { alertService } from '../services/alertService';
import { useToast } from '../hooks/use-toast';
import { addSearch, getHistory } from '../utils/searchHistory';
import { useAuth } from '../contexts/AuthContext';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Bell } from 'lucide-react';

const Home = () => {
  const [jobs, setJobs] = useState([]);
  const [searchQuery, setSearchQuery] = useState({ job: '', location: '', radius: '' });
  const [filters, setFilters] = useState({ job_type: '', posted_within: '', sort: 'created_at', company: '', salary_min: '', is_remote: false });
  const [hasSearched, setHasSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({ page: 1, total: 0, totalPages: 0, limit: 20 });
  const resultsRef = useRef(null);
  const [alertRecent, setAlertRecent] = useState(null); // search obj pending alert
  const [alertEmail, setAlertEmail] = useState('');
  const [alertSubmitting, setAlertSubmitting] = useState(false);
  const [hasHistory, setHasHistory] = useState(() => (getHistory() || []).length > 0);
  const { toast } = useToast();
  const { user, isAuthenticated, isCandidate } = useAuth();
  const location = useLocation();

  useEffect(() => {
    const refresh = () => setHasHistory((getHistory() || []).length > 0);
    window.addEventListener('joboolo-history-changed', refresh);
    return () => window.removeEventListener('joboolo-history-changed', refresh);
  }, []);

  useEffect(() => { loadJobs(); /* eslint-disable-next-line */ }, []);

  // Prefill + auto-search when navigating from /saved-searches with ?q=&l=
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const q = params.get('q') || '';
    const l = params.get('l') || '';
    if (q || l) {
      const query = { job: q, location: l, radius: '' };
      setSearchQuery(query);
      setHasSearched(true);
      loadJobs(query, filters, 1).then(() => scrollToResults());
    }
    // eslint-disable-next-line
  }, [location.search]);

  // Géo-détection : pré-remplit « Où » avec la ville détectée + cookie pays (une seule fois)
  useEffect(() => {
    const hasCookie = document.cookie.includes('joboolo_country=');
    if (hasCookie) return;
    geoService.detect().then((g) => {
      if (g?.country_code) {
        document.cookie = `joboolo_country=${g.country_code};path=/;max-age=${60 * 60 * 24 * 30}`;
      }
      if (g?.city) {
        setSearchQuery((prev) => (prev.location ? prev : { ...prev, location: g.city }));
      }
    }).catch(() => {});
    /* eslint-disable-next-line */
  }, []);

  const buildParams = (query, fltrs, page) => {
    const p = { page, limit: 20, sort: fltrs.sort || 'created_at' };
    if (query.job) p.search = query.job;
    if (query.location) p.location = query.location;
    if (query.radius) p.radius = query.radius;
    if (fltrs.job_type) p.job_type = fltrs.job_type;
    if (fltrs.posted_within) p.posted_within = fltrs.posted_within;
    if (fltrs.company) p.company = fltrs.company;
    if (fltrs.salary_min) p.salary_min = fltrs.salary_min;
    if (fltrs.is_remote) p.is_remote = true;
    return p;
  };

  const loadJobs = async (query = searchQuery, fltrs = filters, page = 1) => {
    setLoading(true);
    try {
      const response = await jobService.searchJobs(buildParams(query, fltrs, page));
      setJobs(response.jobs);
      setPagination({ page: response.page, total: response.total, totalPages: response.total_pages, limit: response.limit });
    } catch (error) {
      toast({ title: 'Erreur', description: "Impossible de charger les offres d'emploi", variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const scrollToResults = () => {
    setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
  };

  const handleSearch = async (query) => {
    setSearchQuery(query);
    setHasSearched(true);
    addSearch({ job: query.job, location: query.location });
    await loadJobs(query, filters, 1);
    scrollToResults();
  };

  const handleFilterChange = async (newFilters) => {
    setFilters(newFilters);
    await loadJobs(searchQuery, newFilters, 1);
  };

  const handlePageChange = async (page) => {
    await loadJobs(searchQuery, filters, page);
    scrollToResults();
  };

  // From sidebar (similar/nearby) or recent searches
  const handleRunSearch = (query) => {
    const q = { job: query.job || '', location: query.location || '', radius: '' };
    handleSearch(q);
  };

  const handleRecentToAlert = (s) => {
    setAlertRecent(s);
    // Pre-fill email for connected candidates
    setAlertEmail((isAuthenticated && isCandidate && user?.email) ? user.email : '');
  };

  const submitRecentAlert = async (e) => {
    e.preventDefault();
    if (!alertEmail) return;
    setAlertSubmitting(true);
    try {
      await alertService.subscribe({ email: alertEmail, search: alertRecent.job || null, location: alertRecent.location || null, origin: 'recent_searches' });
      toast({ title: 'Alerte créée', description: 'Vous recevrez les nouvelles offres par email.' });
      setAlertRecent(null);
    } catch (err) {
      toast({ title: 'Erreur', description: err.message, variant: 'destructive' });
    } finally {
      setAlertSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-white">
      <Header />
      <SearchSection onSearch={handleSearch} initialQuery={searchQuery} hidePopular={hasHistory} />
      <RecentSearches onRun={handleRunSearch} onCreateAlert={handleRecentToAlert} />
      {!hasSearched && !hasHistory && <WhyJoboolo />}
      <div ref={resultsRef} />
      <JobList
        jobs={jobs}
        searchQuery={searchQuery}
        loading={loading}
        pagination={pagination}
        filters={filters}
        onFilterChange={handleFilterChange}
        onPageChange={handlePageChange}
        onRunSearch={handleRunSearch}
      />
      <Footer />
      <BackToTop />
      {hasSearched && <AlertSlider searchQuery={searchQuery} resultCount={pagination.total} />}

      <Dialog open={!!alertRecent} onOpenChange={(o) => { if (!o) setAlertRecent(null); }}>
        <DialogContent className="sm:max-w-md" data-testid="recent-alert-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading flex items-center gap-2">
              <Bell className="h-5 w-5 text-brand" />Créer une alerte email
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-500">
            Soyez averti dès qu'une nouvelle offre « {[alertRecent?.job, alertRecent?.location].filter(Boolean).join(' · ') || 'toutes les offres'} » est publiée.
          </p>
          <form onSubmit={submitRecentAlert} className="space-y-3">
            <Input
              type="email" required value={alertEmail}
              onChange={(e) => setAlertEmail(e.target.value)}
              placeholder="Votre email"
              data-testid="recent-alert-email"
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAlertRecent(null)}>Annuler</Button>
              <Button type="submit" className="bg-brand hover:bg-brand-hover" disabled={alertSubmitting} data-testid="recent-alert-submit">
                {alertSubmitting ? 'Création...' : "Créer l'alerte"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Home;
