import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { paymentService } from '../services/paymentService';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { CheckCircle2, XCircle, Loader2, Wallet } from 'lucide-react';

const MAX_POLLS = 8;

const PaymentSuccess = () => {
  const navigate = useNavigate();
  const [state, setState] = useState('checking'); // checking | paid | pending | error
  const [amount, setAmount] = useState(null);
  const [kind, setKind] = useState(null);
  const [postings, setPostings] = useState(null);
  const pollsRef = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get('session_id');
    if (!sessionId) { setState('error'); return; }

    let timer;
    const poll = async () => {
      try {
        const res = await paymentService.getStatus(sessionId);
        setAmount(res.amount);
        setKind(res.kind);
        setPostings(res.postings);
        if (res.payment_status === 'paid') { setState('paid'); return; }
        if (res.status === 'expired' || res.payment_status === 'failed') { setState('error'); return; }
        pollsRef.current += 1;
        if (pollsRef.current >= MAX_POLLS) { setState('pending'); return; }
        timer = setTimeout(poll, 2000);
      } catch {
        pollsRef.current += 1;
        if (pollsRef.current >= MAX_POLLS) { setState('error'); return; }
        timer = setTimeout(poll, 2000);
      }
    };
    poll();
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4" data-testid="payment-success-page">
      <Card className="w-full max-w-md rounded-2xl">
        <CardContent className="p-8 text-center">
          {state === 'checking' && (
            <>
              <Loader2 className="h-12 w-12 text-brand mx-auto animate-spin mb-4" />
              <h1 className="font-heading text-2xl font-bold text-slate-900">Confirmation du paiement...</h1>
              <p className="text-slate-500 mt-2">Merci de patienter quelques secondes.</p>
            </>
          )}
          {state === 'paid' && (
            <>
              <CheckCircle2 className="h-14 w-14 text-emerald-500 mx-auto mb-4" data-testid="payment-success-icon" />
              <h1 className="font-heading text-2xl font-bold text-slate-900">Paiement réussi 🎉</h1>
              {kind === 'recruiter_pack' ? (
                <>
                  <p className="text-slate-500 mt-2">
                    {postings ? `${postings} offre(s) Premium ont été créditée(s) sur votre compte.` : 'Votre pack a été crédité.'}
                  </p>
                  <Button className="mt-6 bg-brand hover:bg-brand-hover" onClick={() => navigate('/post-job')} data-testid="payment-back-dashboard">
                    <Wallet className="h-4 w-4 mr-2" />Publier mon offre
                  </Button>
                </>
              ) : (
                <>
                  <p className="text-slate-500 mt-2">
                    Votre solde a été crédité{amount ? ` de ${Number(amount).toFixed(2)} €` : ''}.
                  </p>
                  <Button className="mt-6 bg-brand hover:bg-brand-hover" onClick={() => navigate('/partenaire')} data-testid="payment-back-dashboard">
                    <Wallet className="h-4 w-4 mr-2" />Retour à mon espace
                  </Button>
                </>
              )}
            </>
          )}
          {state === 'pending' && (
            <>
              <Loader2 className="h-12 w-12 text-amber-500 mx-auto mb-4" />
              <h1 className="font-heading text-2xl font-bold text-slate-900">Paiement en cours de traitement</h1>
              <p className="text-slate-500 mt-2">Votre solde sera crédité sous peu. Vous pouvez rafraîchir votre espace dans un instant.</p>
              <Button className="mt-6 bg-brand hover:bg-brand-hover" onClick={() => navigate('/partenaire')}>Retour à mon espace</Button>
            </>
          )}
          {state === 'error' && (
            <>
              <XCircle className="h-14 w-14 text-rose-500 mx-auto mb-4" />
              <h1 className="font-heading text-2xl font-bold text-slate-900">Un problème est survenu</h1>
              <p className="text-slate-500 mt-2">Impossible de confirmer le paiement. Contactez-nous si le montant a été débité.</p>
              <Button className="mt-6" variant="outline" onClick={() => navigate('/partenaire')}>Retour à mon espace</Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default PaymentSuccess;
