import api from './api';

export const userService = {
  // Update current user's profile
  async updateProfile(data) {
    try {
      const response = await api.put('/auth/me', data);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to update profile');
    }
  },
};
