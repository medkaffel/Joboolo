import React, { useState } from 'react';
import { Bell, Send } from 'lucide-react';
import { alertService } from '../services/alertService';
import { useToast } from '../hooks/use-toast';
import { useAuth } from '../contexts/AuthContext';

// Inline email alert subscription block. searchQuery: { job, location }
// variant: 'banner' (full width) | 'compact' (sidebar)
const AlertInlineBlock = ({ searchQuery = {}, variant = 'banner', resultCount = null }) => {
  const { toast } = useToast();
  const { user } = useAuth();
  const [email, setEmail] = useState(user?.email || '');
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  const term = searchQuery.job || 'ces offres';

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
        origin: window.location.pathname,
      });
      setDone(true);
      toast({ title: 'Alerte créée', description: 'Vous recevrez les nouvelles offres par email.' });
    } catch (err) {
      toast({ title: 'Erreur', description: err.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const isCompact = variant === 'compact';

  if (done) {
    return (
      <div className={`rounded-2xl bg-emerald-50 border border-emerald-100 ${isCompact ? 'p-4' : 'p-6'} text-center`} data-testid="alert-block-done">
        <Bell className="h-6 w-6 text-emerald-600 mx-auto mb-2" />
        <p className="text-sm text-emerald-800 font-medium">Alerte activée pour « {term} » 🎉</p>
      </div>
    );
  }

  return (
    <div
      className={`rounded-2xl border ${isCompact ? 'p-4 bg-white border-slate-100' : 'p-6 bg-gradient-to-r from-brand/5 to-emerald-50 border-brand/10'}`}
      data-testid={`alert-inline-block-${variant}`}
    >
      <div className={`flex items-center gap-2 mb-1 ${isCompact ? '' : 'justify-center'}`}>
        <Bell className="h-5 w-5 text-brand" />
        <h3 className="font-heading font-semibold text-slate-900 text-sm">Recevez ces offres par email</h3>
      </div>
      <p className={`text-xs text-slate-500 mb-3 ${isCompact ? '' : 'text-center'}`}>
        Soyez averti dès qu'une nouvelle offre « {term} » est publiée.
      </p>
      <form onSubmit={submit} className={`flex ${isCompact ? 'flex-col' : 'flex-col sm:flex-row max-w-md mx-auto'} gap-2`}>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Votre email"
          className="flex-1 h-10 px-4 rounded-full border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
          data-testid={`alert-email-input-${variant}`}
        />
        <button
          type="submit"
          disabled={loading}
          className="h-10 px-5 rounded-full bg-brand hover:bg-brand-hover text-white text-sm font-semibold flex items-center justify-center gap-1 transition-colors"
          data-testid={`alert-submit-${variant}`}
        >
          <Send className="h-4 w-4" />{loading ? '...' : 'Envoyer'}
        </button>
      </form>
      <p className={`text-[10px] text-slate-400 mt-2 ${isCompact ? '' : 'text-center'}`}>
        En cliquant sur « Envoyer », vous acceptez les CGU et notre politique de confidentialité.
      </p>
    </div>
  );
};

export default AlertInlineBlock;
