import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { aiService } from '../services/aiService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ScoreRing } from '../components/MatchDialog';
import { Sparkles, MapPin, Building, Loader2, RefreshCw, UserCog } from 'lucide-react';

const Recommendations = () => {
  const { isAuthenticated, isCandidate } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);

  const load = () => {
    setLoading(true);
    aiService.getRecommendations()
      .then(setData)
      .catch((e) => toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (isAuthenticated && isCandidate) load();
    else setLoading(false);
  }, [isAuthenticated, isCandidate]); // eslint-disable-line

  if (!isAuthenticated || !isCandidate) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="reco-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux candidats</h1>
          <p className="text-slate-500">Connectez-vous avec un compte candidat pour voir vos recommandations.</p>
        </div>
        <Footer />
      </div>
    );
  }

  const recos = data?.recommendations || [];

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="recommendations-page">
        <div className="mb-8 flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
              <Sparkles className="h-7 w-7 text-brand" />Offres recommandées
            </h1>
            <p className="text-slate-500 mt-1">Sélectionnées par l'IA selon votre profil et vos compétences.</p>
          </div>
          <Button variant="outline" onClick={load} disabled={loading} data-testid="reco-refresh-btn">
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />Actualiser
          </Button>
        </div>

        {data && !data.profile_complete && (
          <Card className="mb-6 border-amber-200 bg-amber-50">
            <CardContent className="p-4 flex items-center justify-between gap-4 flex-wrap">
              <p className="text-sm text-amber-800">
                Complétez votre profil (compétences, bio, expérience) pour des recommandations plus précises.
              </p>
              <Button size="sm" variant="outline" onClick={() => navigate('/profile')} data-testid="reco-complete-profile-btn">
                <UserCog className="h-4 w-4 mr-2" />Compléter mon profil
              </Button>
            </CardContent>
          </Card>
        )}

        {loading ? (
          <div className="py-20 flex flex-col items-center text-slate-500" data-testid="reco-loading">
            <Loader2 className="h-8 w-8 animate-spin text-brand mb-3" />
            <p>L'IA analyse les meilleures offres pour vous…</p>
          </div>
        ) : recos.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-slate-400" data-testid="reco-empty">
              <Sparkles className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="mb-4">Aucune recommandation pour le moment.</p>
              <Button onClick={() => navigate('/')} data-testid="reco-browse-btn">Parcourir les offres</Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4" data-testid="reco-list">
            {recos.map(({ job, score, reason }) => (
              <Card key={job.id} className="hover:shadow-lg transition-shadow cursor-pointer"
                onClick={() => navigate(`/jobs/${job.id}`)} data-testid={`reco-item-${job.id}`}>
                <CardContent className="p-5 flex items-center gap-5">
                  {score != null && <ScoreRing score={score} size={64} />}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-slate-900 truncate">{job.title}</h3>
                      {job.is_new && <Badge className="bg-green-100 text-green-800">Nouveau</Badge>}
                      {job.is_remote && <Badge variant="outline" className="bg-brand/10 text-brand">Télétravail</Badge>}
                    </div>
                    <div className="flex items-center text-sm text-slate-500 mt-1">
                      <Building className="h-4 w-4 mr-1" /><span className="mr-3 truncate">{job.company?.name}</span>
                      <MapPin className="h-4 w-4 mr-1" /><span className="truncate">{job.location}</span>
                    </div>
                    {reason && (
                      <p className="text-sm text-brand mt-2 flex items-start gap-1.5">
                        <Sparkles className="h-4 w-4 mt-0.5 shrink-0" />{reason}
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
};

export default Recommendations;
