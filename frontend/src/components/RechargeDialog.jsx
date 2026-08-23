import React, { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { paymentService } from '../services/paymentService';
import { useToast } from '../hooks/use-toast';
import { CreditCard, Loader2 } from 'lucide-react';

// partnerId: pass when an admin recharges a specific partner; omit for partner self-service
// billingMode: 'per_click' (buy € balance) | 'per_posting' (buy job-posting packs)
export const RechargeDialog = ({ open, onOpenChange, partnerId = null, companyName = '', billingMode = 'per_click', postingPrice = 0 }) => {
  const { toast } = useToast();
  const [packs, setPacks] = useState([]);
  const [postingPacks, setPostingPacks] = useState([]);
  const [bounds, setBounds] = useState({ min: 10, max: 5000 });
  const [selected, setSelected] = useState(null); // pack id | 'custom' | number (postings)
  const [custom, setCustom] = useState('');
  const [loading, setLoading] = useState(false);

  const isPosting = billingMode === 'per_posting';

  useEffect(() => {
    if (open) {
      paymentService.getPacks().then((d) => {
        setPacks(d.packs || []);
        setPostingPacks(d.posting_packs || []);
        setBounds({ min: d.min, max: d.max });
      }).catch(() => {});
      setSelected(null);
      setCustom('');
    }
  }, [open]);

  const startCheckout = async () => {
    let opts = {};
    if (isPosting) {
      if (!selected) { toast({ title: 'Sélectionnez un pack d\'annonces', variant: 'destructive' }); return; }
      opts.postings = selected;
    } else if (selected === 'custom') {
      const amt = parseFloat(custom);
      if (!amt || amt < bounds.min || amt > bounds.max) {
        toast({ title: 'Montant invalide', description: `Entre ${bounds.min} € et ${bounds.max} €`, variant: 'destructive' });
        return;
      }
      opts.amount = amt;
    } else if (selected) {
      opts.pack_id = selected;
    } else {
      toast({ title: 'Sélectionnez un montant', variant: 'destructive' });
      return;
    }
    if (partnerId) opts.partner_id = partnerId;

    setLoading(true);
    try {
      const { checkout_url } = await paymentService.createTopup(opts);
      window.location.href = checkout_url;
    } catch (e) {
      setLoading(false);
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="recharge-dialog">
        <DialogHeader>
          <DialogTitle className="font-heading flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-brand" />
            {isPosting ? "Acheter des annonces" : "Recharger le solde"}{companyName ? ` — ${companyName}` : ''}
          </DialogTitle>
        </DialogHeader>

        {isPosting ? (
          <div className="space-y-4">
            <Label className="text-slate-600">Choisissez un pack d'annonces{postingPrice ? ` (${postingPrice.toFixed(2)} €/annonce)` : ''}</Label>
            <div className="grid grid-cols-3 gap-3">
              {postingPacks.map((n) => (
                <button
                  key={n}
                  onClick={() => setSelected(n)}
                  className={`rounded-xl border-2 px-3 py-4 text-center transition-all ${selected === n ? 'border-brand bg-brand/5' : 'border-slate-200 hover:border-brand/40'}`}
                  data-testid={`recharge-postings-${n}`}
                >
                  <div className="font-heading text-xl font-bold text-slate-900">{n}</div>
                  <div className="text-[11px] text-slate-500">annonces</div>
                  {postingPrice > 0 && <div className="text-xs text-brand font-semibold mt-1">{(n * postingPrice).toFixed(0)} €</div>}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <Label className="text-slate-600">Choisissez un pack</Label>
              <div className="grid grid-cols-2 gap-3 mt-2">
                {packs.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setSelected(p.id)}
                    className={`rounded-xl border-2 px-4 py-4 text-left transition-all ${selected === p.id ? 'border-brand bg-brand/5' : 'border-slate-200 hover:border-brand/40'}`}
                    data-testid={`recharge-pack-${p.id}`}
                  >
                    <div className="font-heading text-2xl font-bold text-slate-900">{p.amount} €</div>
                    <div className="text-xs text-slate-500">Crédit prépayé</div>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <Label className="text-slate-600">Ou un montant personnalisé</Label>
              <button
                onClick={() => setSelected('custom')}
                className={`w-full mt-2 rounded-xl border-2 px-4 py-3 flex items-center gap-3 transition-all ${selected === 'custom' ? 'border-brand bg-brand/5' : 'border-slate-200 hover:border-brand/40'}`}
                data-testid="recharge-custom-select"
              >
                <span className="text-sm text-slate-600 shrink-0">Montant libre :</span>
                <Input
                  type="number"
                  min={bounds.min}
                  max={bounds.max}
                  step="1"
                  value={custom}
                  onChange={(e) => { setCustom(e.target.value); setSelected('custom'); }}
                  onClick={(e) => e.stopPropagation()}
                  placeholder={`${bounds.min} – ${bounds.max}`}
                  className="h-9"
                  data-testid="recharge-custom-amount"
                />
                <span className="text-slate-600">€</span>
              </button>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>Annuler</Button>
          <Button className="bg-brand hover:bg-brand-hover" onClick={startCheckout} disabled={loading} data-testid="recharge-pay-btn">
            {loading ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" />Redirection...</> : 'Payer avec Stripe'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default RechargeDialog;
