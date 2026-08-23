import api from './api';

// IMPORTANT for uploads: we must NOT set a hard "Content-Type: multipart/form-data"
// header, otherwise axios keeps that literal value and strips the required
// "; boundary=..." parameter → the backend can't parse the multipart body and
// upload endpoints return 4xx/5xx (which the CDN can even mask as a 520).
// The safest cross-version pattern is to let the browser/axios set the header
// automatically from the FormData body (transformRequest returning FormData
// preserves it; explicit `Content-Type: undefined` forces axios to compute it).
const MULTIPART_CONFIG = {
  headers: { 'Content-Type': undefined },
  transformRequest: [(data) => data], // prevent JSON serialisation of FormData
};

export const fileService = {
  // Upload a CV file; onProgress(percent) optional
  async uploadCV(file, onProgress) {
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.post('/files/upload-cv', form, {
        ...MULTIPART_CONFIG,
        onUploadProgress: (e) => {
          if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total));
        },
      });
      return res.data; // { storage_path, original_filename, content_type }
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Échec de l\'upload du CV');
    }
  },

  // Upload a profile photo
  async uploadProfilePhoto(file) {
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.post('/files/upload-profile-photo', form, MULTIPART_CONFIG);
      return res.data; // { profile_photo_url, ... }
    } catch (error) {
      throw new Error(error.response?.data?.detail || "Échec de l'upload de la photo");
    }
  },

  // ---- Candidate documents (CV + cover letters, max 3 each) ----
  async listCandidateDocuments() {
    const res = await api.get('/files/candidate-documents');
    return res.data;
  },

  async uploadCandidateDocument({ file, category, title = '', description = '' }) {
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.post('/files/candidate-documents', form, {
        ...MULTIPART_CONFIG,
        params: { category, title, description },
      });
      return res.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Échec de l\'upload du document');
    }
  },

  async updateCandidateDocument(id, { title, description }) {
    try {
      const res = await api.put(`/files/candidate-documents/${id}`, { title, description });
      return res.data;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Échec de la mise à jour');
    }
  },

  async deleteCandidateDocument(id) {
    try {
      await api.delete(`/files/candidate-documents/${id}`);
      return true;
    } catch (error) {
      throw new Error(error.response?.data?.detail || 'Échec de la suppression');
    }
  },

  // Fetch a stored file as a blob and open it in a new tab (auth via interceptor)
  async openFile(storagePath) {
    try {
      const res = await api.get(`/files/${storagePath}`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
      throw new Error('Impossible d\'ouvrir le fichier');
    }
  },
};
