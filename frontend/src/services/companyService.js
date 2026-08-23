import api from './api';

const normalize = (c) => ({ ...c, id: c.id || c._id });

export const companyService = {
  async getMyCompanies() {
    try {
      const response = await api.get('/companies/user/my-companies');
      return response.data.map(normalize);
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get companies');
    }
  },

  async createCompany(data) {
    try {
      const response = await api.post('/companies', data);
      return normalize(response.data);
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to create company');
    }
  },
};
