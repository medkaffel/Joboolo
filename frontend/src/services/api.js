import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_BACKEND_URL;
const API_URL = `${API_BASE_URL}/api`;

// Create axios instance
const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token to requests if available
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url || '';
    // Les appels d'authentification (login/register/google) gèrent eux-mêmes
    // leurs erreurs dans le formulaire : on ne redirige JAMAIS pour eux.
    const isAuthCall = /\/auth\/(login|register|register-partner|google)/.test(url);
    if (status === 401 && !isAuthCall) {
      // Session expirée sur une ressource protégée : on nettoie et on renvoie
      // à l'accueil (qui contient la modale de connexion), jamais vers /login.
      const hadToken = !!localStorage.getItem('token');
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      if (hadToken && window.location.pathname !== '/') {
        window.location.href = '/';
      }
    }
    return Promise.reject(error);
  }
);

export default api;