import api from './api';

export const aiService = {
  async getRecommendations() {
    const { data } = await api.get('/ai/recommendations');
    return data;
  },
  async matchJob(jobId) {
    const { data } = await api.post(`/ai/match/${jobId}`);
    return data;
  },
  async matchApplication(applicationId) {
    const { data } = await api.get(`/ai/match/application/${applicationId}`);
    return data;
  },
};
