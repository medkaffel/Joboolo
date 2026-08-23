import React, { useState, useEffect } from 'react';
import { X, Bell, Send } from 'lucide-react';
import { alertService } from '../services/alertService';
import { useToast } from '../hooks/use-toast';
import { useAuth } from '../contexts/AuthContext';

// Slide-in alert invitation shown once per session after results are displayed.
const AlertSlider = ({ searchQuery = {}, resultCount = null }) => {
  const { toast } = useToast();
  const { user, isAuthenticated, isCandidate } = useAuth();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  const term = searchQuery.job || '';

  useEffect(() => {
    if (!term && !searchQuery.location) return;
    if (sessionStorage.getItem('joboolo_slider_dismissed')) return;
    const t = setTimeout(() => setOpen(true), 2500);
    return () => clearTimeout(t);
  }, [term, searchQuery.location]);

  // Pre-fill email for connected candidates
  useEffect(() => {
    if (isAuthenticated && isCandidate && user?.email && !email) setEmail(user.email);
    // eslint-disable-next-line
  }, [isAuthenticated, isCandidate, user?.email]);

  const dismiss = () => {
    setOpen(false);
    sessionStorage.setItem('joboolo_slider_dismissed', '1');
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!email) return;
    setLoading(true);
    try {
      await alertService.subscribe({
        email,
        search: searchQuery.job || null,
        location: searchQuery.location || null,
        search_mode: 'simple',
        result_count: resultCount,
        origin: 'slider',
      });
      setDone(true);
      toast({ title: 'Alerte créée', description: 'Vous recevrez les nouvelles offres par email.' });
      setTimeout(dismiss, 2000);
    } catch (err) {
      toast({ title: 'Erreur', description: err.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed bottom-6 left-6 z-40 w-[340px] max-w-[calc(100vw-3rem)] rounded-2xl bg-white shadow-2xl border border-slate-100 p-5 animate-fade-up"
      data-testid="alert-slider"
    >
      <button onClick={dismiss} className="absolute top-3 right-3 text-slate-400 hover:text-slate-600" aria-label="Fermer" data-testid="alert-slider-close">
        <X className="h-4 w-4" />
      </button>
      <div className="flex items-center gap-2 mb-1">
        <div className="h-9 w-9 rounded-xl bg-brand/10 text-brand flex items-center justify-center"><Bell className="h-5 w-5" /></div>
        <h3 className="font-heading font-semibold text-slate-900 text-sm">
          {term ? `Offres « ${term} »` : 'Créez votre alerte'}
        </h3>
      </div>
      {done ? (
        <p className="text-sm text-emerald-700 mt-2">Alerte activée 🎉</p>
      ) : (
        <>
          <p className="text-xs text-slate-500 mb-3 mt-1">
            Soyez averti dès qu'une nouvelle offre est publiée.
          </p>
          <form onSubmit={submit} className="flex gap-2">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Votre e-mail"
              className="flex-1 h-10 px-3 rounded-full border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
              data-testid="alert-slider-email"
            />
            <button type="submit" disabled={loading} className="h-10 px-4 rounded-full bg-brand hover:bg-brand-hover text-white text-sm font-semibold flex items-center gap-1" data-testid="alert-slider-submit">
              <Send className="h-4 w-4" />
            </button>
          </form>
          <p className="text-[10px] text-slate-400 mt-2">En cliquant sur « Envoyer », vous acceptez les CGU et notre politique de confidentialité.</p>
        </>
      )}
    </div>
  );
};

export default AlertSlider;
