import api from './api';

export const savedJobService = {
  // Save a job
  async saveJob(jobId) {
    try {
      const response = await api.post(`/saved-jobs/${jobId}`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to save job');
    }
  },

  // Remove job from saved
  async unsaveJob(jobId) {
    try {
      const response = await api.delete(`/saved-jobs/${jobId}`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to remove saved job');
    }
  },

  // Get saved jobs
  async getSavedJobs() {
    try {
      const response = await api.get('/saved-jobs');
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get saved jobs');
    }
  },

  // Check if job is saved
  async checkJobSaved(jobId) {
    try {
      const response = await api.get(`/saved-jobs/${jobId}/check`);
      return response.data.is_saved;
    } catch (error) {
      // Return false if error (likely not authenticated)
      return false;
    }
  }
};