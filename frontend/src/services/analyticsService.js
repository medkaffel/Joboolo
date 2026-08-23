import api from './api';

export const analyticsService = {
  async getRecruiterAnalytics() {
    const { data } = await api.get('/analytics/recruiter');
    return data;
  },
};
