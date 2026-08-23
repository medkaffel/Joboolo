import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { applicationService } from '../services/applicationService';
import { aiService } from '../services/aiService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import Footer from '../components/Footer';
import MatchDialog from '../components/MatchDialog';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Briefcase, MapPin, Building, MessageSquare, Sparkles } from 'lucide-react';

const statusMap = {
  pending: { label: 'En attente', color: 'bg-yellow-100 text-yellow-800' },
  reviewed: { label: 'Examinée', color: 'bg-blue-100 text-blue-800' },
  accepted: { label: 'Acceptée', color: 'bg-green-100 text-green-800' },
  rejected: { label: 'Refusée', color: 'bg-red-100 text-red-800' },
};

const MyApplications = () => {
  const { isAuthenticated, isCandidate } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [matchOpen, setMatchOpen] = useState(false);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchResult, setMatchResult] = useState(null);

  const analyzeMatch = async (jobId) => {
    setMatchResult(null);
    setMatchOpen(true);
    setMatchLoading(true);
    try {
      setMatchResult(await aiService.matchJob(jobId));
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
      setMatchOpen(false);
    } finally {
      setMatchLoading(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated && isCandidate) {
      applicationService.getMyApplications()
        .then(setApplications)
        .catch((e) => toast({ title: 'Erreur', description: e.message, variant: 'destructive' }))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [isAuthenticated, isCandidate]);

  if (!isAuthenticated || !isCandidate) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="applications-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux candidats</h1>
          <p className="text-slate-500">Connectez-vous avec un compte candidat pour voir vos candidatures.</p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="my-applications-page">
        <div className="mb-8">
          <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900">Mes candidatures</h1>
          <p className="text-slate-500">Suivez l'état de vos candidatures</p>
        </div>

        {loading ? (
          <p className="text-slate-400">Chargement...</p>
        ) : applications.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-slate-400" data-testid="applications-empty">
              <Briefcase className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="mb-4">Vous n'avez pas encore postulé à une offre.</p>
              <Button onClick={() => navigate('/')} data-testid="applications-discover-btn">Découvrir les offres</Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4" data-testid="applications-list">
            {applications.map((app) => {
              const st = statusMap[app.status] || statusMap.pending;
              return (
                <Card key={app.id} data-testid={`application-item-${app.id}`}>
                  <CardContent className="flex items-center justify-between p-5 gap-4 flex-wrap">
                    <div>
                      <h3 className="font-semibold text-slate-900">{app.job?.title}</h3>
                      <div className="flex items-center text-sm text-slate-500 mt-1">
                        <Building className="h-4 w-4 mr-1" />
                        <span className="mr-3">{app.job?.company?.name}</span>
                        <MapPin className="h-4 w-4 mr-1" />
                        <span>{app.job?.location}</span>
                      </div>
                      <p className="text-xs text-slate-400 mt-1">
                        Envoyée le {new Date(app.created_at).toLocaleDateString('fr-FR')}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Button variant="outline" size="sm" onClick={() => analyzeMatch(app.job?.id)} data-testid={`app-match-btn-${app.id}`}>
                        <Sparkles className="h-4 w-4 mr-1 text-brand" />Ma compatibilité
                      </Button>
                      {app.job?.employer_id && (
                        <Button variant="outline" size="sm" onClick={() => navigate(`/messages?to=${app.job.employer_id}`)} data-testid={`app-contact-btn-${app.id}`}>
                          <MessageSquare className="h-4 w-4 mr-1" />Contacter
                        </Button>
                      )}
                      <Badge className={st.color}>{st.label}</Badge>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
      <MatchDialog open={matchOpen} onOpenChange={setMatchOpen} loading={matchLoading} result={matchResult} title="Ma compatibilité avec l'offre" />
      <Footer />
    </div>
  );
};

export default MyApplications;
