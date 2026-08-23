import React, { useState, useEffect } from 'react';
import { paymentService } from '../services/paymentService';
import { useToast } from '../hooks/use-toast';
import { Card, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Badge } from './ui/badge';
import { Textarea } from './ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog';
import { Megaphone, Plus, Trash2, Play, Pause, Download, Pencil, Search, MapPin, ImagePlus } from 'lucide-react';

const empty = { name: '', billing_mode: 'per_click', cpc: '', cpc_max: '', pack_price: '', xml_feed_url: '', logo_url: '', start_date: '', end_date: '', budget_limit: '' };

const SAMPLE = `<joboolo>
  <ad>
    <id><![CDATA[ 518913 ]]></id>
    <title><![CDATA[ Monteur de pneu ]]></title>
    <content><![CDATA[ Démonter et monter les pneus... ]]></content>
    <url><![CDATA[ https://exemple.fr/job/518913 ]]></url>
    <contract><![CDATA[ Intérim ]]></contract>
    <postcode><![CDATA[ 42680 ]]></postcode>
    <city><![CDATA[ Andrézieux-Bouthéon ]]></city>
    <date><![CDATA[ 26/07/2026 ]]></date>
  </ad>
</joboolo>`;

const PartnerCampaigns = () => {
  const { toast } = useToast();
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [logoUploading, setLogoUploading] = useState(false);
  const [importFor, setImportFor] = useState(null);
  const [importXml, setImportXml] = useState('');
  const [importing, setImporting] = useState(false);
  const [history, setHistory] = useState([]);
  const [jobsFor, setJobsFor] = useState(null);
  const [jobsList, setJobsList] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);

  const load = () => {
    paymentService.listCampaigns().then(setList).catch(() => {});
    paymentService.partnerImports().then(setHistory).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const isClick = form.billing_mode === 'per_click';

  const openCreate = () => { setEditId(null); setForm(empty); setOpen(true); };
  const openEdit = (c) => {
    setEditId(c.id);
    setForm({
      name: c.name || '',
      billing_mode: c.billing_mode || 'per_click',
      cpc: c.cpc ?? '',
      cpc_max: c.cpc_max ?? '',
      pack_price: c.pack_price ?? '',
      xml_feed_url: c.xml_feed_url || '',
      logo_url: c.logo_url || '',
      start_date: c.start_date || '',
      end_date: c.end_date || '',
      budget_limit: c.budget_limit ?? '',
    });
    setOpen(true);
  };

  const save = async () => {
    if (!form.name.trim()) { toast({ title: 'Nom requis', variant: 'destructive' }); return; }
    if (!form.xml_feed_url.trim()) { toast({ title: 'URL du flux XML requise', description: 'Le flux XML est obligatoire.', variant: 'destructive' }); return; }
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        billing_mode: form.billing_mode,
        xml_feed_url: form.xml_feed_url,
        logo_url: form.logo_url || null,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
      };
      if (isClick) {
        payload.cpc = form.cpc ? parseFloat(form.cpc) : null;
        payload.cpc_max = form.cpc_max ? parseFloat(form.cpc_max) : null;
        payload.budget_limit = form.budget_limit ? parseFloat(form.budget_limit) : null;
      } else {
        payload.pack_price = form.pack_price ? parseFloat(form.pack_price) : null;
      }
      if (editId) {
        await paymentService.updateCampaign(editId, payload);
        toast({ title: 'Campagne mise à jour' });
      } else {
        await paymentService.createCampaign(payload);
        toast({ title: 'Campagne créée' });
      }
      setOpen(false); setForm(empty); setEditId(null); load();
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setSaving(false); }
  };

  const uploadLogo = async (file) => {
    if (!file) return;
    setLogoUploading(true);
    try {
      if (editId) {
        const r = await paymentService.uploadCampaignLogo(editId, file);
        set({ logo_url: r.logo_url });
        toast({ title: 'Logo mis à jour' });
        load();
      } else {
        // For a new campaign, store on the partner profile temporarily is not ideal;
        // we upload as campaign logo only after creation. Ask user to save first.
        toast({ title: 'Enregistrez d\'abord la campagne', description: 'Créez la campagne puis modifiez-la pour ajouter un logo.', });
      }
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setLogoUploading(false); }
  };

  const viewJobs = async (c) => {
    setJobsFor(c); setJobsList([]); setJobsLoading(true);
    try {
      const r = await paymentService.campaignJobs(c.id);
      setJobsList(r);
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setJobsLoading(false); }
  };

  const toggle = async (c) => {
    await paymentService.updateCampaign(c.id, { status: c.status === 'active' ? 'paused' : 'active' });
    load();
  };
  const remove = async (c) => {
    if (!window.confirm('Supprimer cette campagne ?')) return;
    await paymentService.deleteCampaign(c.id); load();
  };

  const runImport = async () => {
    setImporting(true);
    try {
      const r = await paymentService.importCampaign(importFor.id, importXml || null);
      toast({ title: 'Import terminé', description: `${r.imported} importée(s), ${r.updated} mise(s) à jour, ${r.skipped_no_credit} sans crédit` });
      setImportFor(null); setImportXml(''); load();
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setImporting(false); }
  };

  return (
    <div data-testid="partner-campaigns">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-heading text-xl font-semibold text-slate-900 flex items-center gap-2">
          <Megaphone className="h-5 w-5 text-brand" /> Mes campagnes d'affichage
        </h2>
        <Button className="bg-brand hover:bg-brand-hover" onClick={openCreate} data-testid="new-campaign-btn">
          <Plus className="h-4 w-4 mr-1" />Nouvelle campagne
        </Button>
      </div>
      <p className="text-sm text-slate-500 mb-3">Chaque campagne a son propre flux XML et son propre mode de facturation (CPC ou pack). Lancez autant de campagnes que nécessaire.</p>

      <Card className="rounded-2xl mb-8">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead><TableHead>Facturation</TableHead><TableHead>CPC / Pack</TableHead>
              <TableHead>Offres</TableHead><TableHead>Clics</TableHead><TableHead>Dépensé</TableHead>
              <TableHead>Statut</TableHead><TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.length === 0 ? (
              <TableRow><TableCell colSpan={8} className="text-center text-slate-400 py-8">Aucune campagne. Créez votre première campagne d'affichage.</TableCell></TableRow>
            ) : list.map((c) => (
              <TableRow key={c.id} data-testid={`campaign-row-${c.id}`}>
                <TableCell className="font-medium">{c.name}</TableCell>
                <TableCell><Badge className="bg-brand/10 text-brand">{c.billing_mode === 'per_click' ? 'Au clic' : "À l'annonce"}</Badge></TableCell>
                <TableCell>{c.billing_mode === 'per_click' ? `${(c.cpc ?? 0).toFixed(2)} €${c.cpc_max ? ` / ${c.cpc_max.toFixed(2)} €` : ''}` : `${(c.pack_price ?? 0).toFixed(2)} €`}</TableCell>
                <TableCell>{c.jobs_count ?? 0}</TableCell>
                <TableCell>{c.clicks}</TableCell>
                <TableCell>{(c.spent ?? 0).toFixed(2)} €{c.budget_limit ? ` / ${c.budget_limit.toFixed(0)} €` : ''}</TableCell>
                <TableCell>
                  {c.status === 'active'
                    ? <Badge className="bg-emerald-100 text-emerald-700">Active</Badge>
                    : <Badge className="bg-slate-200 text-slate-600">En pause</Badge>}
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => viewJobs(c)} title="Voir les offres importées" data-testid={`campaign-view-jobs-${c.id}`}><Search className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => openEdit(c)} title="Modifier la campagne" data-testid={`campaign-edit-${c.id}`}><Pencil className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => { setImportFor(c); setImportXml(''); }} title="Importer le flux XML" data-testid={`campaign-import-${c.id}`}><Download className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => toggle(c)} title={c.status === 'active' ? 'Mettre en pause' : 'Activer'} data-testid={`campaign-toggle-${c.id}`}>
                    {c.status === 'active' ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </Button>
                  <Button variant="ghost" size="sm" className="text-red-500" onClick={() => remove(c)} data-testid={`campaign-delete-${c.id}`}><Trash2 className="h-4 w-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* Import history — last 30 days */}
      <h3 className="font-heading text-lg font-semibold text-slate-900 mb-3">Historique des imports (30 derniers jours)</h3>
      <Card className="rounded-2xl mb-8" data-testid="import-history">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Campagne</TableHead><TableHead>Début</TableHead><TableHead>Fin</TableHead>
              <TableHead>Nouvelles annonces</TableHead><TableHead>Déclenchement</TableHead><TableHead>Statut</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {history.length === 0 ? (
              <TableRow><TableCell colSpan={6} className="text-center text-slate-400 py-8">Aucun import sur les 30 derniers jours</TableCell></TableRow>
            ) : history.map((h, i) => (
              <TableRow key={i} data-testid={`import-log-${i}`}>
                <TableCell className="font-medium">{h.campaign_name}</TableCell>
                <TableCell className="text-slate-500 text-xs">{h.started_at ? new Date(h.started_at).toLocaleString('fr-FR') : '—'}</TableCell>
                <TableCell className="text-slate-500 text-xs">{h.finished_at ? new Date(h.finished_at).toLocaleString('fr-FR') : '—'}</TableCell>
                <TableCell><span className="font-semibold text-brand">+{h.new_ads}</span></TableCell>
                <TableCell><Badge className="bg-slate-100 text-slate-600">{h.trigger === 'auto' ? 'Automatique' : 'Manuel'}</Badge></TableCell>
                <TableCell>{h.status === 'success' ? <Badge className="bg-emerald-100 text-emerald-700">OK</Badge> : <Badge className="bg-rose-100 text-rose-700">Erreur</Badge>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* Create / edit campaign dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg" data-testid="campaign-dialog">
          <DialogHeader><DialogTitle className="font-heading">{editId ? 'Modifier la campagne' : "Nouvelle campagne d'affichage"}</DialogTitle></DialogHeader>
          <div className="space-y-3 max-h-[70vh] overflow-auto pr-1">
            <div>
              <Label>Nom de la campagne</Label>
              <Input value={form.name} onChange={(e) => set({ name: e.target.value })} data-testid="campaign-name" />
            </div>
            <div>
              <Label>Méthode de facturation</Label>
              <select value={form.billing_mode} onChange={(e) => set({ billing_mode: e.target.value })} className="w-full h-10 border border-slate-200 rounded-md px-3 text-sm mt-1" data-testid="campaign-billing-mode">
                <option value="per_click">Au clic (CPC)</option>
                <option value="per_posting">Par pack d'annonce</option>
              </select>
            </div>
            {isClick ? (
              <div className="grid grid-cols-3 gap-3">
                <div><Label>CPC (€)</Label><Input type="number" step="0.01" value={form.cpc} onChange={(e) => set({ cpc: e.target.value })} data-testid="campaign-cpc" /></div>
                <div><Label>CPC max (€)</Label><Input type="number" step="0.01" value={form.cpc_max} onChange={(e) => set({ cpc_max: e.target.value })} data-testid="campaign-cpc-max" /></div>
                <div><Label>Budget (€)</Label><Input type="number" step="1" value={form.budget_limit} onChange={(e) => set({ budget_limit: e.target.value })} data-testid="campaign-budget" /></div>
              </div>
            ) : (
              <div>
                <Label>Prix du pack (€ / annonce)</Label>
                <Input type="number" step="0.01" value={form.pack_price} onChange={(e) => set({ pack_price: e.target.value })} data-testid="campaign-pack-price" />
                <p className="text-xs text-slate-400 mt-1">La durée de validité des annonces est définie par l'administrateur.</p>
              </div>
            )}
            <div>
              <Label>URL du flux XML <span className="text-red-500">*</span></Label>
              <Input value={form.xml_feed_url} onChange={(e) => set({ xml_feed_url: e.target.value })} placeholder="https://votre-site.fr/flux.xml" data-testid="campaign-feed-url" required />
              <p className="text-xs text-slate-400 mt-1">Champ obligatoire. Le flux sera rafraîchi automatiquement.</p>
            </div>
            <div>
              <Label>Logo de la campagne</Label>
              <div className="flex items-center gap-3 mt-1">
                {form.logo_url ? (
                  <img src={`${process.env.REACT_APP_BACKEND_URL}${form.logo_url}`} alt="logo" className="h-10 max-w-[120px] object-contain border rounded" />
                ) : (
                  <span className="text-xs text-slate-400">Aucun logo (celui du profil partenaire sera utilisé)</span>
                )}
                <label className="inline-flex items-center gap-1 text-sm text-brand cursor-pointer">
                  <ImagePlus className="h-4 w-4" />
                  <input type="file" accept="image/*" className="hidden" onChange={(e) => uploadLogo(e.target.files?.[0])} disabled={logoUploading} data-testid="campaign-logo-input" />
                  {logoUploading ? 'Envoi...' : (editId ? 'Choisir un logo' : 'Après création')}
                </label>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Date de démarrage</Label><Input type="date" value={form.start_date} onChange={(e) => set({ start_date: e.target.value })} data-testid="campaign-start" /></div>
              <div><Label>Date d'arrêt</Label><Input type="date" value={form.end_date} onChange={(e) => set({ end_date: e.target.value })} data-testid="campaign-end" /></div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={save} disabled={saving} data-testid="campaign-save">{saving ? '...' : (editId ? 'Enregistrer' : 'Créer')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Campaign jobs dialog (magnifying glass) */}
      <Dialog open={!!jobsFor} onOpenChange={(o) => { if (!o) { setJobsFor(null); setJobsList([]); } }}>
        <DialogContent className="sm:max-w-2xl" data-testid="campaign-jobs-dialog">
          <DialogHeader><DialogTitle className="font-heading">Offres importées — {jobsFor?.name}</DialogTitle></DialogHeader>
          <div className="max-h-[65vh] overflow-auto">
            {jobsLoading ? (
              <p className="text-sm text-slate-400 py-8 text-center">Chargement...</p>
            ) : jobsList.length === 0 ? (
              <p className="text-sm text-slate-400 py-8 text-center" data-testid="campaign-jobs-empty">Aucune offre importée par cette campagne.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow><TableHead>Titre</TableHead><TableHead>Lieu</TableHead><TableHead>Contrat</TableHead><TableHead>Statut</TableHead></TableRow>
                </TableHeader>
                <TableBody>
                  {jobsList.map((j) => (
                    <TableRow key={j.id} data-testid={`campaign-job-${j.id}`}>
                      <TableCell className="font-medium">{j.title}</TableCell>
                      <TableCell className="text-slate-500 text-sm">{j.location}</TableCell>
                      <TableCell><Badge className="bg-slate-100 text-slate-600">{j.job_type}</Badge></TableCell>
                      <TableCell>{j.is_active ? <Badge className="bg-emerald-100 text-emerald-700">Active</Badge> : <Badge className="bg-slate-200 text-slate-600">Inactive</Badge>}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Import dialog (per campaign) */}
      <Dialog open={!!importFor} onOpenChange={(o) => { if (!o) { setImportFor(null); setImportXml(''); } }}>
        <DialogContent className="sm:max-w-2xl" data-testid="campaign-import-dialog">
          <DialogHeader><DialogTitle className="font-heading">Importer le flux — {importFor?.name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">
              Collez le XML au format Joboolo ci-dessous, ou laissez vide pour récupérer depuis l'URL configurée
              {importFor?.xml_feed_url ? ` (${importFor.xml_feed_url})` : ' (aucune URL configurée)'}. CPC appliqué : {(importFor?.cpc ?? 0).toFixed?.(2) || importFor?.cpc || 0} €.
            </p>
            <Textarea value={importXml} onChange={(e) => setImportXml(e.target.value)} rows={10} className="font-mono text-xs" placeholder={SAMPLE} data-testid="campaign-import-textarea" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setImportFor(null); setImportXml(''); }}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={runImport} disabled={importing} data-testid="campaign-import-submit">
              <Download className="h-4 w-4 mr-1" />{importing ? 'Import en cours...' : "Lancer l'import"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PartnerCampaigns;
