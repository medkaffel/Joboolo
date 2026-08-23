import api from './api';

export const jobService = {
  // Search jobs with filters
  async searchJobs(params = {}) {
    try {
      const queryParams = new URLSearchParams();
      
      Object.keys(params).forEach(key => {
        if (params[key] !== null && params[key] !== undefined && params[key] !== '') {
          queryParams.append(key, params[key]);
        }
      });

      const response = await api.get(`/jobs?${queryParams.toString()}`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to search jobs');
    }
  },

  // Get all jobs
  async getAllJobs(page = 1, limit = 20) {
    try {
      const response = await api.get(`/jobs?page=${page}&limit=${limit}&sort=created_at`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get jobs');
    }
  },

  // Get job by ID
  async getJobById(jobId) {
    try {
      const response = await api.get(`/jobs/${jobId}`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get job');
    }
  },

  // Record a click on a partner job and get the external redirect URL
  async recordClick(jobId) {
    const response = await api.post(`/jobs/${jobId}/click`);
    return response.data; // { redirect_url }
  },

  // Record real impressions (partner jobs shown in results)
  async recordImpressions(jobIds) {
    try {
      return (await api.post('/jobs/impressions', { job_ids: jobIds })).data;
    } catch {
      return null;
    }
  },

  // Autocomplete suggestions from existing data
  async suggest(q, field = 'title') {
    try {
      const response = await api.get(`/jobs/suggest?q=${encodeURIComponent(q)}&field=${field}`);
      return response.data.suggestions || [];
    } catch {
      return [];
    }
  },

  // Create new job (employers only)
  async createJob(jobData) {
    try {
      const response = await api.post('/jobs', jobData);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to create job');
    }
  },

  // Update job (employers only)
  async updateJob(jobId, jobData) {
    try {
      const response = await api.put(`/jobs/${jobId}`, jobData);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to update job');
    }
  },

  // Delete job (employers only)
  async deleteJob(jobId) {
    try {
      await api.delete(`/jobs/${jobId}`);
      return { success: true };
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to delete job');
    }
  },

  // Get jobs by company
  async getJobsByCompany(companyId) {
    try {
      const response = await api.get(`/jobs/company/${companyId}`);
      return response.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Failed to get company jobs');
    }
  },

  // All jobs owned by the current employer (active + inactive)
  async getMyJobs() {
    const response = await api.get('/jobs/mine');
    return response.data;
  },

  // Activate/deactivate own job
  async toggleJob(jobId) {
    return (await api.post(`/jobs/${jobId}/toggle`)).data;
  }
};