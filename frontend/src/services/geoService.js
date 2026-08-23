import api from './api';

export const geoService = {
  async detect() {
    try {
      return (await api.get('/geo/detect')).data;
    } catch {
      return {};
    }
  },
  async autocomplete(q) {
    try {
      return (await api.get('/geo/autocomplete', { params: { q } })).data.suggestions || [];
    } catch {
      return [];
    }
  },
};
