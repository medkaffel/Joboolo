import api from './api';

export const alertService = {
  async createAlert(data) {
    try {
      const response = await api.post('/alerts', data);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to create alert');
    }
  },

  async getMyAlerts() {
    try {
      const response = await api.get('/alerts');
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get alerts');
    }
  },

  async updateAlert(alertId, data) {
    try {
      const response = await api.put(`/alerts/${alertId}`, data);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to update alert');
    }
  },

  async deleteAlert(alertId) {
    try {
      const response = await api.delete(`/alerts/${alertId}`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to delete alert');
    }
  },

  async sendNow(alertId) {
    try {
      const response = await api.post(`/alerts/${alertId}/send-now`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to send alert');
    }
  },

  // Public: subscribe to an alert by email (creates a lightweight account if needed)
  async subscribe(payload) {
    try {
      const response = await api.post('/alerts/subscribe', payload);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to subscribe');
    }
  },
};
