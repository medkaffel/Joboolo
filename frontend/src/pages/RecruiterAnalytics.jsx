import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { analyticsService } from '../services/analyticsService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { BarChart3, Eye, FileText, Briefcase, TrendingUp, Loader2 } from 'lucide-react';

const STATUS = {
  pending: { label: 'En attente', color: 'bg-yellow-100 text-yellow-800' },
  reviewed: { label: 'Examinées', color: 'bg-blue-100 text-blue-800' },
  accepted: { label: 'Acceptées', color: 'bg-green-100 text-green-800' },
  rejected: { label: 'Refusées', color: 'bg-red-100 text-red-800' },
};

const StatCard = ({ icon: Icon, label, value, testid }) => (
  <Card data-testid={testid}>
    <CardContent className="p-5 flex items-center gap-4">
      <span className="flex items-center justify-center h-12 w-12 rounded-xl bg-brand/10 text-brand">
        <Icon className="h-6 w-6" />
      </span>
      <div>
        <p className="text-2xl font-bold text-slate-900">{value}</p>
        <p className="text-sm text-slate-500">{label}</p>
      </div>
    </CardContent>
  </Card>
);

const RecruiterAnalytics = () => {
  const { isAuthenticated, isEmployer } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (isAuthenticated && isEmployer) {
      analyticsService.getRecruiterAnalytics()
        .then(setData)
        .catch((e) => toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [isAuthenticated, isEmployer]); // eslint-disable-line

  if (!isAuthenticated || !isEmployer) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="analytics-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux employeurs</h1>
        </div>
        <Footer />
      </div>
    );
  }

  const maxTimeline = Math.max(1, ...((data?.timeline || []).map((d) => d.count)));

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="recruiter-analytics-page">
        <div className="mb-8">
          <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
            <BarChart3 className="h-7 w-7 text-brand" />Statistiques
          </h1>
          <p className="text-slate-500 mt-1">Vues et candidatures de vos offres.</p>
        </div>

        {loading ? (
          <div className="py-20 flex justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand" /></div>
        ) : !data ? (
          <p className="text-slate-400">Aucune donnée.</p>
        ) : (
          <div className="space-y-8">
            {/* Totals */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="analytics-totals">
              <StatCard icon={Briefcase} label="Offres publiées" value={data.totals.jobs} testid="stat-jobs" />
              <StatCard icon={TrendingUp} label="Offres actives" value={data.totals.active_jobs} testid="stat-active" />
              <StatCard icon={Eye} label="Vues totales" value={data.totals.views} testid="stat-views" />
              <StatCard icon={FileText} label="Candidatures" value={data.totals.applications} testid="stat-apps" />
            </div>

            {/* Status breakdown */}
            <Card>
              <CardContent className="p-5">
                <h2 className="font-semibold text-slate-900 mb-4">Répartition des candidatures</h2>
                <div className="flex flex-wrap gap-3" data-testid="status-breakdown">
                  {Object.entries(STATUS).map(([key, s]) => (
                    <div key={key} className={`rounded-lg px-4 py-3 ${s.color}`}>
                      <p className="text-xl font-bold">{data.status_totals?.[key] ?? 0}</p>
                      <p className="text-xs">{s.label}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Timeline */}
            <Card>
              <CardContent className="p-5">
                <h2 className="font-semibold text-slate-900 mb-4">Candidatures (14 derniers jours)</h2>
                <div className="flex items-end gap-1.5 h-40" data-testid="analytics-timeline">
                  {data.timeline.map((d) => (
                    <div key={d.date} className="flex-1 flex flex-col items-center justify-end group">
                      <div className="w-full bg-brand/80 rounded-t hover:bg-brand transition-colors relative"
                        style={{ height: `${(d.count / maxTimeline) * 100}%`, minHeight: d.count ? '4px' : '0' }}>
                        <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[10px] text-slate-600 opacity-0 group-hover:opacity-100">
                          {d.count}
                        </span>
                      </div>
                      <span className="text-[9px] text-slate-400 mt-1">{d.date.slice(8, 10)}/{d.date.slice(5, 7)}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Per job */}
            <Card>
              <CardContent className="p-5">
                <h2 className="font-semibold text-slate-900 mb-4">Performance par offre</h2>
                {data.per_job.length === 0 ? (
                  <p className="text-slate-400 text-sm">Vous n'avez pas encore publié d'offre.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm" data-testid="per-job-table">
                      <thead>
                        <tr className="text-left text-slate-400 border-b">
                          <th className="py-2 pr-4">Offre</th>
                          <th className="py-2 px-2 text-center">Vues</th>
                          <th className="py-2 px-2 text-center">Candidatures</th>
                          <th className="py-2 px-2 text-center">Conversion</th>
                          <th className="py-2 pl-2 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.per_job.map((j) => (
                          <tr key={j.id} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`per-job-row-${j.id}`}>
                            <td className="py-3 pr-4">
                              <span className="font-medium text-slate-900">{j.title}</span>
                              {!j.is_active && <Badge className="ml-2 bg-slate-100 text-slate-500">Inactive</Badge>}
                            </td>
                            <td className="py-3 px-2 text-center">{j.views}</td>
                            <td className="py-3 px-2 text-center font-semibold">{j.applications}</td>
                            <td className="py-3 px-2 text-center text-slate-500">{j.conversion}%</td>
                            <td className="py-3 pl-2 text-right">
                              <Button size="sm" variant="outline" onClick={() => navigate(`/my-jobs/${j.id}/applications`)}
                                data-testid={`view-apps-${j.id}`}>Voir</Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
};

export default RecruiterAnalytics;
