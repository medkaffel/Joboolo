import api from './api';

export const messageService = {
  async getConversations() {
    const { data } = await api.get('/messages/conversations');
    return data;
  },
  async getThread(otherId) {
    const { data } = await api.get(`/messages/thread/${otherId}`);
    return data;
  },
  async send({ recipient_id, text, job_id = null }) {
    const { data } = await api.post('/messages', { recipient_id, text, job_id });
    return data;
  },
  async unreadCount() {
    try {
      const { data } = await api.get('/messages/unread-count');
      return data.count || 0;
    } catch {
      return 0;
    }
  },
};
