import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { applicationService } from '../services/applicationService';
import { jobService } from '../services/jobService';
import { fileService } from '../services/fileService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { ArrowLeft, Download, Mail, User, FileText } from 'lucide-react';

const STATUS = {
  pending: { label: 'En attente', color: 'bg-yellow-100 text-yellow-800' },
  reviewed: { label: 'Examinée', color: 'bg-blue-100 text-blue-800' },
  accepted: { label: 'Acceptée', color: 'bg-green-100 text-green-800' },
  rejected: { label: 'Refusée', color: 'bg-red-100 text-red-800' },
};

const ApplicationsForJob = () => {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const { isAuthenticated, isEmployer } = useAuth();
  const { toast } = useToast();
  const [apps, setApps] = useState([]);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isAuthenticated && isEmployer) {
      Promise.all([
        applicationService.getJobApplications(jobId),
        jobService.getJobById(jobId).catch(() => null),
      ]).then(([a, j]) => { setApps(a); setJob(j); })
        .catch((e) => toast({ title: 'Erreur', description: e.message, variant: 'destructive' }))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [isAuthenticated, isEmployer, jobId]);

  const changeStatus = async (appId, status) => {
    try {
      const updated = await applicationService.updateApplicationStatus(appId, status);
      setApps((prev) => prev.map((a) => (a.id === appId ? { ...a, status: updated.status || status } : a)));
      toast({ title: 'Statut mis à jour', description: STATUS[status].label });
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    }
  };

  const downloadCv = async (path) => {
    try { await fileService.openFile(path); }
    catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
  };

  if (!isAuthenticated || !isEmployer) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="apps-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux employeurs</h1>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="applications-for-job-page">
        <Button variant="ghost" onClick={() => navigate('/my-jobs')} className="mb-4 text-slate-500" data-testid="apps-back-btn">
          <ArrowLeft className="h-4 w-4 mr-2" />Retour à mes offres
        </Button>

        <div className="mb-8">
          <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900">Candidatures</h1>
          <p className="text-slate-500">{job?.title ? `Pour l'offre : ${job.title}` : 'Offre'}</p>
        </div>

        {loading ? (
          <p className="text-slate-400">Chargement...</p>
        ) : apps.length === 0 ? (
          <Card><CardContent className="py-16 text-center text-slate-400" data-testid="apps-empty">
            <User className="h-12 w-12 mx-auto mb-4 opacity-50" />
            Aucune candidature pour cette offre pour l'instant.
          </CardContent></Card>
        ) : (
          <div className="space-y-4" data-testid="applications-list">
            {apps.map((app) => {
              const st = STATUS[app.status] || STATUS.pending;
              const c = app.candidate || {};
              return (
                <Card key={app.id} data-testid={`application-card-${app.id}`}>
                  <CardContent className="p-5">
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold text-slate-900">{c.first_name} {c.last_name}</h3>
                          <Badge className={st.color}>{st.label}</Badge>
                        </div>
                        <a href={`mailto:${c.email}`} className="flex items-center text-sm text-brand mt-1">
                          <Mail className="h-4 w-4 mr-1" />{c.email}
                        </a>
                        {c.location && <p className="text-xs text-slate-400 mt-1">{c.location}</p>}
                      </div>
                      <div className="flex items-center gap-2">
                        {app.cv_url ? (
                          <Button variant="outline" size="sm" onClick={() => downloadCv(app.cv_url)} data-testid={`app-download-cv-${app.id}`}>
                            <Download className="h-4 w-4 mr-1" />CV
                          </Button>
                        ) : (
                          <span className="text-xs text-gray-400 flex items-center"><FileText className="h-4 w-4 mr-1" />Pas de CV</span>
                        )}
                        <Select value={app.status} onValueChange={(v) => changeStatus(app.id, v)}>
                          <SelectTrigger className="w-36" data-testid={`app-status-select-${app.id}`}><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {Object.entries(STATUS).map(([val, s]) => (
                              <SelectItem key={val} value={val}>{s.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    {app.cover_letter && (
                      <div className="mt-3 bg-gray-50 rounded-md p-3">
                        <p className="text-sm text-gray-700 whitespace-pre-line">{app.cover_letter}</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
};

export default ApplicationsForJob;
