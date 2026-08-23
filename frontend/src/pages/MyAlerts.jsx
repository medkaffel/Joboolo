import React from 'react';
import Header from '../components/Header';
import Footer from '../components/Footer';
import AlertsManager from '../components/AlertsManager';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useEffect } from 'react';

const MyAlerts = () => {
  const { isAuthenticated, isCandidate, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && (!isAuthenticated || !isCandidate)) {
      navigate('/');
    }
  }, [loading, isAuthenticated, isCandidate, navigate]);

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <Header />
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <h1 className="font-heading text-3xl font-extrabold text-slate-900 mb-6">Mes alertes emploi</h1>
        <p className="text-slate-500 mb-8">Gérez vos alertes email : créez, modifiez la fréquence, activez/désactivez ou supprimez.</p>
        <AlertsManager />
      </main>
      <Footer />
    </div>
  );
};

export default MyAlerts;
