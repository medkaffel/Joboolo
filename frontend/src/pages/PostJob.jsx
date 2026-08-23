import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { companyService } from '../services/companyService';
import { jobService } from '../services/jobService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Checkbox } from '../components/ui/checkbox';
import { Briefcase, MapPin } from 'lucide-react';
import AutocompleteInput from '../components/AutocompleteInput';

const PostJob = () => {
  const { isAuthenticated, isEmployer } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const editId = searchParams.get('edit');

  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    company_id: '',
    new_company_name: '',
    new_company_industry: '',
    new_company_location: '',
    title: '',
    description: '',
    location: '',
    job_type: 'CDI',
    salary_min: '',
    salary_max: '',
    is_remote: false,
    is_urgent: false,
  });

  useEffect(() => {
    if (isAuthenticated && isEmployer) {
      companyService.getMyCompanies().then(setCompanies).catch(() => {});
    }
  }, [isAuthenticated, isEmployer]);

  // Edit mode: preload the job to modify
  useEffect(() => {
    if (!editId || !isAuthenticated || !isEmployer) return;
    jobService.getMyJobs().then((all) => {
      const j = all.find((x) => x.id === editId);
      if (!j) { toast({ title: 'Offre introuvable', variant: 'destructive' }); navigate('/my-jobs'); return; }
      setForm((p) => ({
        ...p,
        company_id: j.company?.id || '',
        title: j.title || '',
        description: j.description || '',
        location: j.location || '',
        job_type: j.job_type || 'CDI',
        salary_min: j.salary_min ?? '',
        salary_max: j.salary_max ?? '',
        is_remote: !!j.is_remote,
        is_urgent: !!j.is_urgent,
      }));
    }).catch(() => {});
    // eslint-disable-next-line
  }, [editId, isAuthenticated, isEmployer]);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      // Edit mode: update existing job
      if (editId) {
        await jobService.updateJob(editId, {
          title: form.title,
          description: form.description,
          location: form.location,
          job_type: form.job_type,
          salary_min: form.salary_min ? parseInt(form.salary_min) : null,
          salary_max: form.salary_max ? parseInt(form.salary_max) : null,
          is_remote: form.is_remote,
          is_urgent: form.is_urgent,
        });
        toast({ title: 'Offre mise à jour' });
        navigate('/my-jobs');
        return;
      }

      let companyId = form.company_id;

      if (!companyId) {
        if (!form.new_company_name.trim()) {
          throw new Error('Veuillez sélectionner ou créer une entreprise');
        }
        const company = await companyService.createCompany({
          name: form.new_company_name,
          industry: form.new_company_industry || null,
          location: form.new_company_location || null,
        });
        companyId = company.id;
      }

      await jobService.createJob({
        company_id: companyId,
        title: form.title,
        description: form.description,
        location: form.location,
        job_type: form.job_type,
        salary_min: form.salary_min ? parseInt(form.salary_min) : null,
        salary_max: form.salary_max ? parseInt(form.salary_max) : null,
        is_remote: form.is_remote,
        is_urgent: form.is_urgent,
      });

      toast({ title: 'Offre publiée', description: 'Votre offre est maintenant en ligne !' });
      navigate('/my-jobs');
    } catch (err) {
      toast({ title: 'Erreur', description: err.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  if (!isAuthenticated || !isEmployer) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="post-job-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Accès réservé aux employeurs</h1>
          <p className="text-slate-500">Connectez-vous avec un compte employeur pour publier une offre.</p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="post-job-page">
        <div className="mb-8">
          <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900">{editId ? "Modifier l'offre" : 'Publier une offre'}</h1>
          <p className="text-slate-500">Décrivez le poste pour attirer les meilleurs candidats</p>
        </div>

        <form onSubmit={handleSubmit}>
          {!editId && (
          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="flex items-center space-x-2">
                <Briefcase className="h-5 w-5" /><span>Entreprise</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {companies.length > 0 && (
                <div>
                  <Label>Entreprise existante</Label>
                  <Select value={form.company_id} onValueChange={(v) => set('company_id', v)}>
                    <SelectTrigger data-testid="post-job-company-select"><SelectValue placeholder="Sélectionner une entreprise" /></SelectTrigger>
                    <SelectContent>
                      {companies.map((c) => (
                        <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              {!form.company_id && (
                <div className="space-y-4 border-t pt-4">
                  <p className="text-sm text-slate-400">Ou créez une nouvelle entreprise :</p>
                  <div>
                    <Label htmlFor="cname">Nom de l'entreprise</Label>
                    <Input id="cname" data-testid="post-job-new-company-name" value={form.new_company_name} onChange={(e) => set('new_company_name', e.target.value)} placeholder="Ex: Joboolo SAS" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label htmlFor="cind">Secteur</Label>
                      <Input id="cind" value={form.new_company_industry} onChange={(e) => set('new_company_industry', e.target.value)} placeholder="Ex: Tech" />
                    </div>
                    <div>
                      <Label htmlFor="cloc">Localisation</Label>
                      <AutocompleteInput
                        value={form.new_company_location}
                        onChange={(v) => set('new_company_location', v)}
                        field="location"
                        icon={MapPin}
                        placeholder="Ville, département ou région"
                        testId="post-job-company-location"
                        inputClassName="w-full h-10 pl-10 pr-3 py-2 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1"
                      />
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
          )}

          <Card className="mb-6">
            <CardHeader><CardTitle>Détails du poste</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label htmlFor="title">Intitulé du poste</Label>
                <Input id="title" data-testid="post-job-title" value={form.title} onChange={(e) => set('title', e.target.value)} required placeholder="Développeur Full Stack" />
              </div>
              <div>
                <Label htmlFor="location">Localisation</Label>
                <AutocompleteInput
                  value={form.location}
                  onChange={(v) => set('location', v)}
                  field="location"
                  icon={MapPin}
                  placeholder="Ville, département ou code postal"
                  testId="post-job-location"
                  inputClassName="w-full h-10 pl-10 pr-3 py-2 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1"
                />
              </div>
              <div>
                <Label>Type de contrat</Label>
                <Select value={form.job_type} onValueChange={(v) => set('job_type', v)}>
                  <SelectTrigger data-testid="post-job-type"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {['CDI', 'CDD', 'Stage', 'Freelance', 'Intérim'].map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="smin">Salaire min (€/an)</Label>
                  <Input id="smin" type="number" value={form.salary_min} onChange={(e) => set('salary_min', e.target.value)} placeholder="35000" />
                </div>
                <div>
                  <Label htmlFor="smax">Salaire max (€/an)</Label>
                  <Input id="smax" type="number" value={form.salary_max} onChange={(e) => set('salary_max', e.target.value)} placeholder="55000" />
                </div>
              </div>
              <div>
                <Label htmlFor="desc">Description</Label>
                <Textarea id="desc" data-testid="post-job-description" value={form.description} onChange={(e) => set('description', e.target.value)} required rows={6} placeholder="Missions, profil recherché, avantages..." />
              </div>
              <div className="flex items-center gap-6">
                <label className="flex items-center gap-2 cursor-pointer">
                  <Checkbox checked={form.is_remote} onCheckedChange={(v) => set('is_remote', !!v)} data-testid="post-job-remote" />
                  <span className="text-sm">Télétravail</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <Checkbox checked={form.is_urgent} onCheckedChange={(v) => set('is_urgent', !!v)} data-testid="post-job-urgent" />
                  <span className="text-sm">Urgent</span>
                </label>
              </div>
            </CardContent>
          </Card>

          <div className="flex justify-end gap-3">
            <Button type="button" variant="outline" onClick={() => navigate('/my-jobs')}>Annuler</Button>
            <Button type="submit" disabled={loading} data-testid="post-job-submit">
              {loading ? 'Enregistrement...' : (editId ? "Enregistrer les modifications" : "Publier l'offre")}
            </Button>
          </div>
        </form>
      </div>
      <Footer />
    </div>
  );
};

export default PostJob;
