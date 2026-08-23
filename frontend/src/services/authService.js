import api from './api';
import { getAttribution } from '../utils/attribution';

// Message d'erreur d'authentification convivial (FR) affiché sur les formulaires.
export const friendlyAuthError = (msg) => {
  if (!msg) return 'Une erreur est survenue. Veuillez réessayer.';
  if (/incorrect email or password|login failed|invalid credentials/i.test(msg)) {
    return "L'identifiant ou le mot de passe est erroné.";
  }
  return msg;
};

export const authService = {
  // Register new user
  async register(userData) {
    try {
      const response = await api.post('/auth/register', { ...userData, ...getAttribution() });
      const { user, token } = response.data;
      
      // Store token and user data
      localStorage.setItem('token', token.access_token);
      localStorage.setItem('user', JSON.stringify(user));
      
      return { user, token };
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Registration failed');
    }
  },

  // Partner self-registration (pending admin validation, no auto-login)
  async registerPartner(data) {
    try {
      const response = await api.post('/auth/register-partner', { ...data, ...getAttribution() });
      return response.data; // { pending: true, message }
    } catch (error) {
      throw new Error(error.response?.data?.detail || "Échec de l'inscription");
    }
  },

  // Login user
  async login(credentials) {
    try {
      const response = await api.post('/auth/login', credentials);
      const { user, token } = response.data;
      
      // Store token and user data
      localStorage.setItem('token', token.access_token);
      localStorage.setItem('user', JSON.stringify(user));
      
      return { user, token };
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Login failed');
    }
  },

  // Logout user
  logout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/';
  },

  // Get current user from localStorage
  getCurrentUser() {
    const userStr = localStorage.getItem('user');
    return userStr ? JSON.parse(userStr) : null;
  },

  // Get token from localStorage
  getToken() {
    return localStorage.getItem('token');
  },

  // Check if user is authenticated
  isAuthenticated() {
    return !!this.getToken();
  },

  // Get current user profile from server
  async getProfile() {
    try {
      const response = await api.get('/auth/me');
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get profile');
    }
  },

  // Exchange Emergent Google session_id for app JWT
  async googleSession(sessionId) {
    try {
      const response = await api.post('/auth/google/session', { session_id: sessionId });
      const { user, token } = response.data;
      localStorage.setItem('token', token.access_token);
      localStorage.setItem('user', JSON.stringify(user));
      return { user, token };
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Google login failed');
    }
  }
};