import React, { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog';
import { Button } from './ui/button';
import { recruiterService } from '../services/recruiterService';
import { useToast } from '../hooks/use-toast';
import { CreditCard, Loader2, Check } from 'lucide-react';

// Dialogue d'achat d'offres Premium à l'unité (paiement Stripe)
export const RecruiterCheckoutDialog = ({ open, onOpenChange, initialPackId = 'premium_1' }) => {
  const { toast } = useToast();
  const [packs, setPacks] = useState([]);
  const [selected, setSelected] = useState(initialPackId);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      recruiterService.getPacks().then((d) => setPacks(d.packs || [])).catch(() => {});
      setSelected(initialPackId);
    }
  }, [open, initialPackId]);

  const startCheckout = async () => {
    if (!selected) { toast({ title: 'Sélectionnez un pack', variant: 'destructive' }); return; }
    setLoading(true);
    try {
      const { checkout_url } = await recruiterService.checkout(selected);
      window.location.href = checkout_url;
    } catch (e) {
      setLoading(false);
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="recruiter-checkout-dialog">
        <DialogHeader>
          <DialogTitle className="font-heading flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-brand" />
            Choisissez votre pack d'offres Premium
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {packs.map((p) => {
            const unit = (p.price / p.postings);
            const isSel = selected === p.id;
            return (
              <button
                key={p.id}
                onClick={() => setSelected(p.id)}
                className={`w-full rounded-xl border-2 px-4 py-4 flex items-center justify-between text-left transition-all ${isSel ? 'border-brand bg-brand/5' : 'border-slate-200 hover:border-brand/40'}`}
                data-testid={`recruiter-pack-${p.id}`}
              >
                <div>
                  <div className="font-heading text-lg font-bold text-slate-900">{p.label}</div>
                  <div className="text-xs text-slate-500">{unit.toFixed(0)} € / offre · Mise en avant 30 jours</div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-heading text-xl font-bold text-brand">{p.price.toFixed(0)} €</span>
                  <span className={`h-5 w-5 rounded-full flex items-center justify-center border ${isSel ? 'bg-brand border-brand text-white' : 'border-slate-300 text-transparent'}`}>
                    <Check className="h-3.5 w-3.5" />
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>Annuler</Button>
          <Button className="bg-brand hover:bg-brand-hover" onClick={startCheckout} disabled={loading} data-testid="recruiter-pay-btn">
            {loading ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" />Redirection...</> : 'Payer avec Stripe'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default RecruiterCheckoutDialog;
