import React, { useEffect, useState } from 'react';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { getHistory, removeSearch, clearHistory } from '../utils/searchHistory';
import { Bell, Trash2, Search, History } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { alertService } from '../services/alertService';
import { useToast } from '../hooks/use-toast';

const SavedSearches = () => {
  const { isAuthenticated, isCandidate, loading } = useAuth();
  const navigate = useNavigate();
  const [list, setList] = useState([]);
  const [alertRow, setAlertRow] = useState(null);
  const [frequency, setFrequency] = useState('daily');
  const [submitting, setSubmitting] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    if (!loading && (!isAuthenticated || !isCandidate)) navigate('/');
  }, [loading, isAuthenticated, isCandidate, navigate]);

  useEffect(() => {
    const refresh = () => setList(getHistory());
    refresh();
    window.addEventListener('joboolo-history-changed', refresh);
    return () => window.removeEventListener('joboolo-history-changed', refresh);
  }, []);

  const label = (s) => [s.job, s.location].filter(Boolean).join(' · ') || 'Toutes les offres';

  const runSearch = (s) => {
    const params = new URLSearchParams();
    if (s.job) params.set('q', s.job);
    if (s.location) params.set('l', s.location);
    navigate(`/?${params.toString()}`);
  };

  const submitAlert = async (e) => {
    e.preventDefault();
    if (!alertRow) return;
    setSubmitting(true);
    try {
      await alertService.createAlert({
        search: alertRow.job || null,
        location: alertRow.location || null,
        frequency,
      });
      toast({ title: 'Alerte créée', description: 'Vous recevrez les nouvelles offres par email.' });
      setAlertRow(null);
    } catch (err) {
      toast({ title: 'Erreur', description: err.message, variant: 'destructive' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <Header />
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <div className="flex items-center justify-between mb-6">
          <h1 className="font-heading text-3xl font-extrabold text-slate-900 flex items-center gap-3">
            <History className="h-7 w-7 text-brand" /> Recherches sauvegardées
          </h1>
          {list.length > 0 && (
            <button
              onClick={() => clearHistory()}
              className="text-sm text-slate-400 hover:text-red-500 transition-colors"
              data-testid="clear-history-btn"
            >
              Tout effacer
            </button>
          )}
        </div>

        {list.length === 0 ? (
          <div className="text-center py-20 bg-slate-50 rounded-2xl">
            <History className="h-12 w-12 text-slate-300 mx-auto mb-4" />
            <p className="text-slate-500 mb-4">Aucune recherche enregistrée pour le moment.</p>
            <Button onClick={() => navigate('/')} className="bg-brand hover:bg-brand-hover">
              Lancer une recherche
            </Button>
          </div>
        ) : (
          <ul className="space-y-3" data-testid="saved-searches-list">
            {list.map((s, i) => (
              <li
                key={i}
                className="flex items-center justify-between bg-white rounded-xl border border-slate-100 px-4 py-3 hover:border-brand/40 transition-colors"
                data-testid={`saved-search-${i}`}
              >
                <button onClick={() => runSearch(s)} className="flex items-center gap-3 text-left flex-1 min-w-0">
                  <Search className="h-4 w-4 text-slate-400 shrink-0" />
                  <span className="text-sm text-slate-700 truncate">{label(s)}</span>
                </button>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => setAlertRow(s)}
                    title="Transformer en alerte"
                    className="h-8 px-3 rounded-lg text-brand hover:bg-brand/10 flex items-center gap-1.5 transition-colors"
                    data-testid={`saved-to-alert-${i}`}
                  >
                    <Bell className="h-4 w-4" />
                    <span className="hidden sm:inline text-sm">Créer alerte</span>
                  </button>
                  <button
                    onClick={() => removeSearch(i)}
                    title="Supprimer"
                    className="h-8 w-8 rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-500 flex items-center justify-center transition-colors"
                    data-testid={`saved-remove-${i}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
      <Footer />

      <Dialog open={!!alertRow} onOpenChange={(o) => { if (!o) setAlertRow(null); }}>
        <DialogContent className="sm:max-w-md" data-testid="saved-alert-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading flex items-center gap-2">
              <Bell className="h-5 w-5 text-brand" />Créer une alerte email
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-500">
            Soyez averti dès qu'une nouvelle offre « {alertRow ? ([alertRow.job, alertRow.location].filter(Boolean).join(' · ') || 'toutes les offres') : ''} » est publiée.
          </p>
          <form onSubmit={submitAlert} className="space-y-3">
            <label className="text-sm text-slate-600">Fréquence</label>
            <select
              value={frequency}
              onChange={(e) => setFrequency(e.target.value)}
              className="w-full h-10 rounded-md border border-slate-200 px-3 text-sm"
              data-testid="saved-alert-frequency"
            >
              <option value="instant">Instantané</option>
              <option value="daily">Quotidien</option>
              <option value="weekly">Hebdomadaire</option>
            </select>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAlertRow(null)}>Annuler</Button>
              <Button type="submit" className="bg-brand hover:bg-brand-hover" disabled={submitting} data-testid="saved-alert-submit">
                {submitting ? 'Création...' : "Créer l'alerte"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default SavedSearches;
