import api from './api';

export const applicationService = {
  // Apply to a job
  async applyToJob(applicationData) {
    try {
      const response = await api.post('/applications', applicationData);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to apply to job');
    }
  },

  // Get user's applications
  async getMyApplications() {
    try {
      const response = await api.get('/applications');
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get applications');
    }
  },

  // Get applications for a job (employers only)
  async getJobApplications(jobId) {
    try {
      const response = await api.get(`/applications/job/${jobId}`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get job applications');
    }
  },

  // Update application status (employers only)
  async updateApplicationStatus(applicationId, status, employerNotes = null) {
    try {
      const response = await api.put(`/applications/${applicationId}/status`, {
        status,
        employer_notes: employerNotes
      });
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to update application status');
    }
  }
};