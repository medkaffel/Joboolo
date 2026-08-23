import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import Header from '../components/Header';
import Footer from '../components/Footer';
import CandidateDocuments from '../components/CandidateDocuments';
import { Button } from '../components/ui/button';
import { ArrowLeft, Mail } from 'lucide-react';

const MyCoverLetters = () => {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès refusé</h1>
          <p className="text-slate-500">Vous devez être connecté pour accéder à cette page.</p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50" data-testid="my-cover-letters-page">
      <Header />
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Button variant="ghost" onClick={() => navigate('/profile')} className="mb-4 -ml-2 text-slate-500" data-testid="back-to-profile">
          <ArrowLeft className="h-4 w-4 mr-1.5" />Retour au profil
        </Button>
        <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
          <Mail className="h-6 w-6 text-brand" />Mes lettres de motivation
        </h1>
        <p className="text-slate-500 mt-1 mb-6">Gérez vos lettres de motivation.</p>
        <CandidateDocuments only="cover_letter" />
      </div>
      <Footer />
    </div>
  );
};

export default MyCoverLetters;
