import React, { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../hooks/use-toast';

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
const AuthCallback = () => {
  const { loginWithGoogleSession } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const match = window.location.hash.match(/session_id=([^&]+)/);
    if (!match) {
      navigate('/');
      return;
    }
    const sessionId = decodeURIComponent(match[1]);

    loginWithGoogleSession(sessionId).then((result) => {
      window.history.replaceState(null, '', window.location.pathname);
      if (result.success) {
        toast({ title: 'Connexion réussie', description: 'Bienvenue sur Joboolo !' });
        navigate('/profile');
      } else {
        toast({ title: 'Erreur', description: result.error, variant: 'destructive' });
        navigate('/');
      }
    });
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50" data-testid="auth-callback">
      <div className="text-center">
        <div className="h-10 w-10 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-gray-600">Connexion en cours...</p>
      </div>
    </div>
  );
};

export default AuthCallback;
