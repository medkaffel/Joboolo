import React, { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';
import { Button } from './ui/button';
import { Label } from './ui/label';
import { Textarea } from './ui/textarea';
import { Progress } from './ui/progress';
import { Upload, FileText, X } from 'lucide-react';
import { fileService } from '../services/fileService';
import { applicationService } from '../services/applicationService';
import { useToast } from '../hooks/use-toast';

const ACCEPTED = ['pdf', 'doc', 'docx'];
const MAX = 10 * 1024 * 1024;

const ApplyModal = ({ isOpen, onClose, job, onApplied }) => {
  const { toast } = useToast();
  const [coverLetter, setCoverLetter] = useState('');
  const [file, setFile] = useState(null);
  const [progress, setProgress] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setCoverLetter(''); setFile(null); setProgress(0); setSubmitting(false);
  };

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const ext = f.name.split('.').pop().toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      toast({ title: 'Format non supporté', description: 'PDF, DOC ou DOCX uniquement', variant: 'destructive' });
      return;
    }
    if (f.size > MAX) {
      toast({ title: 'Fichier trop volumineux', description: 'Max 10 Mo', variant: 'destructive' });
      return;
    }
    setFile(f);
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      let cvUrl = null;
      if (file) {
        setProgress(1);
        const uploaded = await fileService.uploadCV(file, setProgress);
        cvUrl = uploaded.storage_path;
      }
      await applicationService.applyToJob({
        job_id: job.id,
        cover_letter: coverLetter || 'Candidature via Joboolo',
        cv_url: cvUrl,
      });
      toast({ title: 'Candidature envoyée', description: 'Bonne chance ! 🎉' });
      reset();
      onApplied && onApplied();
      onClose();
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(o) => { if (!o) { reset(); onClose(); } }}>
      <DialogContent className="sm:max-w-lg" data-testid="apply-modal">
        <DialogHeader>
          <DialogTitle>Postuler — {job?.title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          <div>
            <Label htmlFor="cover-letter">Lettre de motivation</Label>
            <Textarea
              id="cover-letter"
              data-testid="apply-cover-letter"
              rows={6}
              value={coverLetter}
              onChange={(e) => setCoverLetter(e.target.value)}
              placeholder="Présentez-vous et expliquez pourquoi ce poste vous intéresse..."
            />
          </div>

          <div>
            <Label>CV (PDF, DOC, DOCX — max 10 Mo)</Label>
            {!file ? (
              <label
                htmlFor="cv-file"
                className="mt-1 flex flex-col items-center justify-center border-2 border-dashed border-gray-300 rounded-lg p-6 cursor-pointer hover:border-blue-400 transition-colors"
                data-testid="apply-cv-dropzone"
              >
                <Upload className="h-8 w-8 text-gray-400 mb-2" />
                <span className="text-sm text-gray-600">Cliquez pour choisir votre CV</span>
                <input id="cv-file" type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={handleFile} data-testid="apply-cv-input" />
              </label>
            ) : (
              <div className="mt-1 flex items-center justify-between border rounded-lg p-3" data-testid="apply-cv-selected">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="h-5 w-5 text-blue-600 shrink-0" />
                  <span className="text-sm text-gray-700 truncate">{file.name}</span>
                </div>
                <button onClick={() => setFile(null)} disabled={submitting} className="text-gray-400 hover:text-red-500">
                  <X className="h-4 w-4" />
                </button>
              </div>
            )}
            {submitting && progress > 0 && progress < 100 && (
              <Progress value={progress} className="mt-2" data-testid="apply-cv-progress" />
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" onClick={() => { reset(); onClose(); }} disabled={submitting}>Annuler</Button>
            <Button onClick={handleSubmit} disabled={submitting} className="bg-blue-600 hover:bg-blue-700" data-testid="apply-submit-btn">
              {submitting ? 'Envoi...' : 'Envoyer ma candidature'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ApplyModal;
