import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Textarea } from './ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog';
import { FileText, Mail, Upload, Pencil, Trash2, Download, Search } from 'lucide-react';
import { fileService } from '../services/fileService';
import { relevantJobsHref } from '../utils/cvSearch';
import { useToast } from '../hooks/use-toast';

const CATEGORIES = {
  cv: { label: 'CV', icon: FileText, emptyText: 'Aucun CV enregistré.' },
  cover_letter: { label: 'Lettres de motivation', icon: Mail, emptyText: 'Aucune lettre de motivation enregistrée.' },
};
const MAX = 3;

const CandidateDocuments = ({ only }) => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadFor, setUploadFor] = useState(null); // 'cv' | 'cover_letter'
  const [editFor, setEditFor] = useState(null); // doc object
  const [form, setForm] = useState({ title: '', description: '' });
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const load = async () => {
    setLoading(true);
    try {
      const list = await fileService.listCandidateDocuments();
      setDocs(list || []);
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const byCategory = (cat) => docs.filter((d) => d.category === cat);

  const openUpload = (cat) => {
    setUploadFor(cat);
    setForm({ title: '', description: '' });
    setFile(null);
  };

  const submitUpload = async () => {
    if (!file) { toast({ title: 'Sélectionnez un fichier PDF/DOC/DOCX', variant: 'destructive' }); return; }
    setBusy(true);
    try {
      await fileService.uploadCandidateDocument({ file, category: uploadFor, title: form.title, description: form.description });
      toast({ title: 'Document ajouté' });
      setUploadFor(null); setFile(null); setForm({ title: '', description: '' });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  const submitEdit = async () => {
    setBusy(true);
    try {
      await fileService.updateCandidateDocument(editFor.id, { title: form.title, description: form.description });
      toast({ title: 'Document mis à jour' });
      setEditFor(null);
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  const remove = async (d) => {
    if (!window.confirm(`Supprimer « ${d.title || d.original_filename} » ?`)) return;
    try {
      await fileService.deleteCandidateDocument(d.id);
      toast({ title: 'Document supprimé' });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
  };

  const openFile = async (d) => {
    try { await fileService.openFile(d.storage_path); }
    catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
  };

  const renderCategory = (cat) => {
    const meta = CATEGORIES[cat];
    const list = byCategory(cat);
    const Icon = meta.icon;
    const atMax = list.length >= MAX;
    return (
      <Card className="rounded-2xl" data-testid={`docs-${cat}`}>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon className="h-4 w-4 text-brand" />{meta.label}
            <span className="text-xs font-normal text-slate-400">({list.length}/{MAX})</span>
          </CardTitle>
          <Button size="sm" className="bg-brand hover:bg-brand-hover" disabled={atMax} onClick={() => openUpload(cat)} data-testid={`docs-${cat}-add`}>
            <Upload className="h-4 w-4 mr-1" />Ajouter
          </Button>
        </CardHeader>
        <CardContent className="pt-0">
          {loading ? (
            <div className="text-sm text-slate-400 py-4 text-center">Chargement…</div>
          ) : list.length === 0 ? (
            <div className="text-sm text-slate-400 py-4 text-center">{meta.emptyText}</div>
          ) : (
            <ul className="space-y-2">
              {list.map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-3 border border-slate-100 rounded-lg px-3 py-2.5" data-testid={`docs-${cat}-item-${d.id}`}>
                  <div className="flex-1 min-w-0">
                    <button onClick={() => openFile(d)} className="text-sm font-medium text-brand hover:underline text-left truncate block" title={d.original_filename}>
                      {d.title || d.original_filename}
                    </button>
                    {d.description && <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{d.description}</p>}
                    <p className="text-[11px] text-slate-400 mt-0.5">{d.original_filename}</p>
                    {cat === 'cv' && (
                      <button
                        onClick={() => navigate(relevantJobsHref(d.title || d.original_filename))}
                        className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-brand hover:underline"
                        title="Voir les annonces correspondant à ce CV"
                        data-testid={`docs-cv-relevant-${d.id}`}
                      >
                        <Search className="h-3 w-3" />Annonces pertinentes
                      </button>
                    )}
                  </div>
                  <div className="flex items-center gap-0.5 shrink-0">
                    <button onClick={() => openFile(d)} title="Ouvrir" className="h-8 w-8 rounded-md text-slate-500 hover:bg-slate-100 flex items-center justify-center" data-testid={`docs-${cat}-open-${d.id}`}>
                      <Download className="h-4 w-4" />
                    </button>
                    <button onClick={() => { setEditFor(d); setForm({ title: d.title || '', description: d.description || '' }); }} title="Modifier" className="h-8 w-8 rounded-md text-slate-500 hover:bg-slate-100 flex items-center justify-center" data-testid={`docs-${cat}-edit-${d.id}`}>
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button onClick={() => remove(d)} title="Supprimer" className="h-8 w-8 rounded-md text-rose-500 hover:bg-rose-50 flex items-center justify-center" data-testid={`docs-${cat}-delete-${d.id}`}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <div className={only ? 'space-y-6' : 'grid grid-cols-1 md:grid-cols-2 gap-6'} data-testid="candidate-documents">
      {(!only || only === 'cv') && renderCategory('cv')}
      {(!only || only === 'cover_letter') && renderCategory('cover_letter')}

      {/* Upload dialog */}
      <Dialog open={!!uploadFor} onOpenChange={(o) => !o && setUploadFor(null)}>
        <DialogContent data-testid="docs-upload-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">
              Ajouter — {uploadFor === 'cv' ? 'CV' : 'Lettre de motivation'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Fichier (PDF, DOC ou DOCX — max 10 Mo)</Label>
              <input
                ref={inputRef}
                type="file"
                accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="mt-1 block w-full text-sm text-slate-500 file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-brand/10 file:text-brand hover:file:bg-brand/20"
                data-testid="docs-upload-file"
              />
              {file && <p className="text-xs text-slate-500 mt-1">{file.name} ({(file.size / 1024).toFixed(0)} Ko)</p>}
            </div>
            <div>
              <Label>Titre</Label>
              <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Ex: CV Développeur Full-Stack 2026" data-testid="docs-upload-title" />
            </div>
            <div>
              <Label>Note descriptive (courte)</Label>
              <Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Contexte, version, cible…" data-testid="docs-upload-description" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setUploadFor(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={submitUpload} disabled={busy || !file} data-testid="docs-upload-submit">
              {busy ? 'Envoi…' : 'Enregistrer'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit dialog */}
      <Dialog open={!!editFor} onOpenChange={(o) => !o && setEditFor(null)}>
        <DialogContent data-testid="docs-edit-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">
              Modifier — {editFor?.category === 'cv' ? 'CV' : 'Lettre de motivation'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Titre</Label>
              <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="docs-edit-title" />
            </div>
            <div>
              <Label>Note descriptive</Label>
              <Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="docs-edit-description" />
            </div>
            <p className="text-xs text-slate-400">Fichier : {editFor?.original_filename}</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditFor(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={submitEdit} disabled={busy} data-testid="docs-edit-submit">
              {busy ? 'Envoi…' : 'Enregistrer'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default CandidateDocuments;
