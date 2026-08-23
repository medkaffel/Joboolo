import api from './api';

export const paymentService = {
  async getPacks() {
    return (await api.get('/payments/packs')).data;
  },
  // opts: { pack_id } OR { amount }, plus optional partner_id (admin only)
  async createTopup(opts) {
    const payload = { ...opts, origin_url: window.location.origin };
    return (await api.post('/payments/create-topup', payload)).data;
  },
  async getStatus(sessionId) {
    return (await api.get(`/payments/status/${sessionId}`)).data;
  },
  async partnerMe() {
    return (await api.get('/partner/me')).data;
  },
  async partnerTransactions() {
    return (await api.get('/partner/transactions')).data;
  },
  async partnerImportXml(xmlContent) {
    return (await api.post('/partner/import-xml', { xml_content: xmlContent || null })).data;
  },
  async partnerSetFeedUrl(url) {
    return (await api.put('/partner/feed-url', { xml_feed_url: url || null })).data;
  },
  async partnerPerformance(days = 14) {
    return (await api.get(`/partner/performance?days=${days}`)).data;
  },
  // Partner display campaigns
  async listCampaigns() {
    return (await api.get('/partner/campaigns')).data;
  },
  async createCampaign(data) {
    return (await api.post('/partner/campaigns', data)).data;
  },
  async updateCampaign(id, data) {
    return (await api.put(`/partner/campaigns/${id}`, data)).data;
  },
  async deleteCampaign(id) {
    return (await api.delete(`/partner/campaigns/${id}`)).data;
  },
  async importCampaign(id, xmlContent) {
    return (await api.post(`/partner/campaigns/${id}/import`, { xml_content: xmlContent || null })).data;
  },
  async partnerImports() {
    return (await api.get('/partner/imports')).data;
  },
  async campaignJobs(id) {
    return (await api.get(`/partner/campaigns/${id}/jobs`)).data;
  },
  async uploadPartnerLogo(file) {
    const fd = new FormData();
    fd.append('file', file);
    return (await api.post('/partner/logo', fd, { headers: { 'Content-Type': undefined } })).data;
  },
  async uploadCampaignLogo(id, file) {
    const fd = new FormData();
    fd.append('file', file);
    return (await api.post(`/partner/campaigns/${id}/logo`, fd, { headers: { 'Content-Type': undefined } })).data;
  },
};
