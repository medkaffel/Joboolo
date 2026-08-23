import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { savedJobService } from '../services/savedJobService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import Footer from '../components/Footer';
import JobCard from '../components/JobCard';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Heart } from 'lucide-react';

const SavedJobs = () => {
  const { isAuthenticated, isCandidate } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isAuthenticated && isCandidate) {
      savedJobService.getSavedJobs()
        .then(setJobs)
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
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="saved-jobs-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux candidats</h1>
          <p className="text-slate-500">Connectez-vous avec un compte candidat pour voir vos offres sauvegardées.</p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="saved-jobs-page">
        <div className="mb-8">
          <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900">Emplois sauvegardés</h1>
          <p className="text-slate-500">Retrouvez les offres que vous avez mises de côté</p>
        </div>

        {loading ? (
          <p className="text-slate-400">Chargement...</p>
        ) : jobs.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-slate-400" data-testid="saved-jobs-empty">
              <Heart className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="mb-4">Aucune offre sauvegardée pour le moment.</p>
              <Button onClick={() => navigate('/')} data-testid="saved-jobs-discover-btn">Découvrir les offres</Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4" data-testid="saved-jobs-list">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
};

export default SavedJobs;
