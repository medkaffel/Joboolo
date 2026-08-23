import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Briefcase, Plus, LayoutList, BarChart3, MessageSquare } from 'lucide-react';

const EmployerDashboard = () => {
  const { isAuthenticated, isEmployer, user } = useAuth();
  const navigate = useNavigate();

  if (!isAuthenticated || !isEmployer) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="employer-dashboard-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux employeurs</h1>
          <p className="text-slate-500">Connectez-vous avec un compte employeur pour accéder au tableau de bord.</p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="employer-dashboard-page">
        <div className="mb-8">
          <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900">Bonjour {user?.first_name} 👋</h1>
          <p className="text-slate-500">Gérez votre recrutement sur Joboolo</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card className="hover:shadow-lg transition-shadow cursor-pointer" onClick={() => navigate('/post-job')} data-testid="dashboard-post-job-card">
            <CardHeader>
              <CardTitle className="flex items-center space-x-2"><Plus className="h-5 w-5 text-brand" /><span>Publier une offre</span></CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-slate-500 mb-4">Créez une nouvelle annonce et attirez les meilleurs talents.</p>
              <Button>Publier maintenant</Button>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow cursor-pointer" onClick={() => navigate('/my-jobs')} data-testid="dashboard-my-jobs-card">
            <CardHeader>
              <CardTitle className="flex items-center space-x-2"><LayoutList className="h-5 w-5 text-brand" /><span>Mes offres</span></CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-slate-500 mb-4">Consultez et gérez vos annonces publiées.</p>
              <Button variant="outline"><Briefcase className="h-4 w-4 mr-2" />Voir mes offres</Button>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow cursor-pointer" onClick={() => navigate('/recruiter-analytics')} data-testid="dashboard-analytics-card">
            <CardHeader>
              <CardTitle className="flex items-center space-x-2"><BarChart3 className="h-5 w-5 text-brand" /><span>Statistiques</span></CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-slate-500 mb-4">Suivez les vues et candidatures de vos offres.</p>
              <Button variant="outline"><BarChart3 className="h-4 w-4 mr-2" />Voir les stats</Button>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow cursor-pointer" onClick={() => navigate('/messages')} data-testid="dashboard-messages-card">
            <CardHeader>
              <CardTitle className="flex items-center space-x-2"><MessageSquare className="h-5 w-5 text-brand" /><span>Messagerie</span></CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-slate-500 mb-4">Échangez directement avec vos candidats.</p>
              <Button variant="outline"><MessageSquare className="h-4 w-4 mr-2" />Ouvrir la messagerie</Button>
            </CardContent>
          </Card>
        </div>
      </div>
      <Footer />
    </div>
  );
};

export default EmployerDashboard;
