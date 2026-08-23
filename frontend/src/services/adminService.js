import api from './api';

export const adminService = {
  async stats() {
    return (await api.get('/admin/stats')).data;
  },
  async listUsers(userType, search = '') {
    return (await api.get('/admin/users', { params: { user_type: userType, search } })).data;
  },
  async updateUser(id, data) {
    return (await api.put(`/admin/users/${id}`, data)).data;
  },
  async toggleUser(id) {
    return (await api.post(`/admin/users/${id}/toggle`)).data;
  },
  async deleteUser(id) {
    return (await api.delete(`/admin/users/${id}`)).data;
  },
  async listPartners(search = '') {
    return (await api.get('/admin/partners', { params: { search } })).data;
  },
  async listPendingPartners(search = '') {
    return (await api.get('/admin/partners/pending', { params: { search } })).data;
  },
  async validatePartner(id) {
    return (await api.post(`/admin/partners/${id}/validate`)).data;
  },
  async createPartner(data) {
    return (await api.post('/admin/partners', data)).data;
  },
  async configPartner(userId, data) {
    return (await api.put(`/admin/partners/${userId}/config`, data)).data;
  },
  async importXml(userId, xmlContent) {
    return (await api.post(`/admin/partners/${userId}/import-xml`, { xml_content: xmlContent || null })).data;
  },
  async searchJobs(params) {
    return (await api.get('/admin/jobs', { params })).data;
  },
  async toggleJob(id) {
    return (await api.post(`/admin/jobs/${id}/toggle`)).data;
  },
  async updateJob(id, data) {
    return (await api.put(`/admin/jobs/${id}`, data)).data;
  },
  async deleteJob(id) {
    return (await api.delete(`/admin/jobs/${id}`)).data;
  },
  // Settings
  async getSettings() {
    return (await api.get('/admin/settings')).data;
  },
  async updateSettings(data) {
    return (await api.put('/admin/settings', data)).data;
  },
  // XML feed campaigns
  async listFeeds() {
    return (await api.get('/admin/xml-feeds')).data;
  },
  async createFeed(data) {
    return (await api.post('/admin/xml-feeds', data)).data;
  },
  async updateFeed(id, data) {
    return (await api.put(`/admin/xml-feeds/${id}`, data)).data;
  },
  async importFeed(id) {
    return (await api.post(`/admin/xml-feeds/${id}/import`)).data;
  },
  async deleteFeed(id) {
    return (await api.delete(`/admin/xml-feeds/${id}`)).data;
  },
  // Alerts management
  async listAlerts(params = {}) {
    return (await api.get('/admin/alerts', { params })).data;
  },
  async toggleAlert(id) {
    return (await api.put(`/admin/alerts/${id}/toggle`)).data;
  },
  async deleteAlert(id) {
    return (await api.delete(`/admin/alerts/${id}`)).data;
  },
  // Footer international country links
  async listFooterCountries() {
    return (await api.get('/admin/footer-countries')).data;
  },
  async createFooterCountry(data) {
    return (await api.post('/admin/footer-countries', data)).data;
  },
  async updateFooterCountry(id, data) {
    return (await api.put(`/admin/footer-countries/${id}`, data)).data;
  },
  async deleteFooterCountry(id) {
    return (await api.delete(`/admin/footer-countries/${id}`)).data;
  },
};
