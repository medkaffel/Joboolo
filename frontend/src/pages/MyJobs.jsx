import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { companyService } from '../services/companyService';
import { jobService } from '../services/jobService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Briefcase, MapPin, Eye, Users, Plus, Trash2, Pencil, Power } from 'lucide-react';

const MyJobs = () => {
  const { isAuthenticated, isEmployer } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadJobs = async () => {
    try {
      const all = await jobService.getMyJobs();
      setJobs(all);
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated && isEmployer) {
      loadJobs();
    } else {
      setLoading(false);
    }
  }, [isAuthenticated, isEmployer]);

  const handleDelete = async (jobId) => {
    if (!window.confirm('Supprimer définitivement cette offre ?')) return;
    try {
      await jobService.deleteJob(jobId);
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
      toast({ title: 'Offre supprimée' });
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    }
  };

  const handleToggle = async (jobId) => {
    try {
      const res = await jobService.toggleJob(jobId);
      setJobs((prev) => prev.map((j) => (j.id === jobId ? { ...j, is_active: res.is_active } : j)));
      toast({ title: res.is_active ? 'Offre activée' : 'Offre désactivée' });
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    }
  };

  if (!isAuthenticated || !isEmployer) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="my-jobs-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux employeurs</h1>
          <p className="text-slate-500">Connectez-vous avec un compte employeur pour gérer vos offres.</p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="my-jobs-page">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900">Mes offres</h1>
            <p className="text-slate-500">Gérez vos annonces publiées</p>
          </div>
          <Button onClick={() => navigate('/post-job')} data-testid="my-jobs-post-btn">
            <Plus className="h-4 w-4 mr-2" />Publier une offre
          </Button>
        </div>

        {loading ? (
          <p className="text-slate-400">Chargement...</p>
        ) : jobs.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-slate-400" data-testid="my-jobs-empty">
              <Briefcase className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="mb-4">Vous n'avez pas encore publié d'offre.</p>
              <Button onClick={() => navigate('/post-job')} data-testid="my-jobs-empty-post-btn">Publier ma première offre</Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4" data-testid="my-jobs-list">
            {jobs.map((job) => (
              <Card key={job.id} data-testid={`my-job-item-${job.id}`}>
                <CardContent className="flex items-center justify-between p-5">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-slate-900">{job.title}</h3>
                      <Badge variant="outline" className="text-xs">{job.job_type}</Badge>
                      {job.is_active
                        ? <Badge className="bg-emerald-100 text-emerald-700 text-xs">Active</Badge>
                        : <Badge className="bg-slate-200 text-slate-600 text-xs">Désactivée</Badge>}
                    </div>
                    <div className="flex items-center text-sm text-slate-500 mt-1">
                      <MapPin className="h-4 w-4 mr-1" /><span className="mr-4">{job.location}</span>
                      <Eye className="h-4 w-4 mr-1" /><span className="mr-4">{job.views_count} vues</span>
                      <Users className="h-4 w-4 mr-1" /><span>{job.applications_count} candidatures</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={() => navigate(`/my-jobs/${job.id}/applications`)} data-testid={`my-job-applications-${job.id}`}>
                      <Users className="h-4 w-4 mr-1" />Candidatures ({job.applications_count})
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => navigate(`/post-job?edit=${job.id}`)} data-testid={`my-job-edit-${job.id}`} title="Modifier">
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleToggle(job.id)} data-testid={`my-job-toggle-${job.id}`} title={job.is_active ? 'Désactiver' : 'Activer'}>
                      <Power className="h-4 w-4" />
                    </Button>
                    <Button variant="outline" size="sm" className="text-red-600 border-red-200 hover:bg-red-50"
                      onClick={() => handleDelete(job.id)} data-testid={`my-job-delete-${job.id}`} title="Supprimer">
                      <Trash2 className="h-4 w-4" />
                    </Button>
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

export default MyJobs;
