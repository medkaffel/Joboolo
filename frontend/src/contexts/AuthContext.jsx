import React, { createContext, useContext, useState, useEffect } from 'react';
import { authService } from '../services/authService';
import { userService } from '../services/userService';
import { captureAttribution } from '../utils/attribution';

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Capture signup attribution on first visit
    captureAttribution();
    // Check if user is logged in on app start
    const savedUser = authService.getCurrentUser();
    if (savedUser) {
      setUser(savedUser);
    }
    setLoading(false);
  }, []);

  const login = async (credentials) => {
    try {
      const { user: userData } = await authService.login(credentials);
      setUser(userData);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  const register = async (userData) => {
    try {
      const { user: newUser } = await authService.register(userData);
      setUser(newUser);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  const loginWithOAuth = async (oauthData) => {
    try {
      // Pour la démo, créer un utilisateur avec les données OAuth
      const userData = {
        email: oauthData.email,
        password: 'oauth_temp_password', // Mot de passe temporaire pour OAuth
        first_name: oauthData.first_name,
        last_name: oauthData.last_name,
        user_type: 'candidate',
        oauth_provider: oauthData.provider,
        oauth_id: oauthData.provider_id
      };

      // Essayer de se connecter d'abord (si l'utilisateur existe déjà)
      try {
        const loginResult = await authService.login({
          email: oauthData.email,
          password: 'oauth_temp_password'
        });
        setUser(loginResult.user);
        return { success: true };
      } catch (loginError) {
        // Si la connexion échoue, créer un nouveau compte
        const { user: newUser } = await authService.register(userData);
        setUser(newUser);
        return { success: true };
      }
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  const updateProfile = async (data) => {
    try {
      const updated = await userService.updateProfile(data);
      localStorage.setItem('user', JSON.stringify(updated));
      setUser(updated);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  const loginWithGoogleSession = async (sessionId) => {
    try {
      const { user: userData } = await authService.googleSession(sessionId);
      setUser(userData);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  const logout = () => {
    authService.logout();
    setUser(null);
  };

  const value = {
    user,
    login,
    register,
    loginWithOAuth,
    loginWithGoogleSession,
    updateProfile,
    logout,
    loading,
    isAuthenticated: !!user,
    isCandidate: user?.user_type === 'candidate',
    isEmployer: user?.user_type === 'employer' || user?.user_type === 'admin'
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};