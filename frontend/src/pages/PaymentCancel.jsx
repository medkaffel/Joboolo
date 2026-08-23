import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { XCircle } from 'lucide-react';

const PaymentCancel = () => {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4" data-testid="payment-cancel-page">
      <Card className="w-full max-w-md rounded-2xl">
        <CardContent className="p-8 text-center">
          <XCircle className="h-14 w-14 text-slate-400 mx-auto mb-4" />
          <h1 className="font-heading text-2xl font-bold text-slate-900">Paiement annulé</h1>
          <p className="text-slate-500 mt-2">Aucun montant n'a été débité. Vous pouvez réessayer quand vous le souhaitez.</p>
          <Button className="mt-6 bg-brand hover:bg-brand-hover" onClick={() => navigate('/partenaire')} data-testid="payment-cancel-back">
            Retour à mon espace
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};

export default PaymentCancel;
