import api from './api';

export const recruiterService = {
  async getPacks() {
    return (await api.get('/recruiter/packs')).data;
  },
  async checkout(packId) {
    const payload = { pack_id: packId, origin_url: window.location.origin };
    return (await api.post('/recruiter/checkout', payload)).data;
  },
  async requestQuote(data) {
    return (await api.post('/recruiter/quote', data)).data;
  },
};
