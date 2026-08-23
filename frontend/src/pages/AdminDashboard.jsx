import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { adminService } from '../services/adminService';
import { useToast } from '../hooks/use-toast';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import { Users, Briefcase, Building2, Handshake, Power, Trash2, Plus, Search, Settings, LogOut, Ban, CheckCircle2, Download, CreditCard, Rss, Bell, Save, RefreshCw, Globe, ExternalLink, Pencil } from 'lucide-react';
import { RechargeDialog } from '../components/RechargeDialog';
import { AdminListHeader, DetailDialog, DetailLinkCell } from '../components/admin/AdminListHelpers';

const StatCard = ({ icon: Icon, label, value }) => (
  <Card className="rounded-2xl">
    <CardContent className="p-5 flex items-center gap-4">
      <div className="h-11 w-11 rounded-xl bg-brand/10 text-brand flex items-center justify-center"><Icon className="h-5 w-5" /></div>
      <div>
        <div className="font-heading text-2xl font-bold text-slate-900">{value ?? '—'}</div>
        <div className="text-sm text-slate-500">{label}</div>
      </div>
    </CardContent>
  </Card>
);

// ---------- Login gate ----------
const AdminLogin = () => {
  const { login } = useAuth();
  const { toast } = useToast();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    const res = await login({ email, password });
    setLoading(false);
    if (!res.success) toast({ title: 'Échec', description: res.error, variant: 'destructive' });
    else toast({ title: 'Connecté' });
  };

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <Card className="w-full max-w-md rounded-2xl">
        <CardHeader>
          <CardTitle className="font-heading text-2xl text-center">
            Admin <span className="text-brand">Joboolo</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <Label htmlFor="admin-email">Email</Label>
              <Input id="admin-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required data-testid="admin-email" />
            </div>
            <div>
              <Label htmlFor="admin-password">Mot de passe</Label>
              <Input id="admin-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required data-testid="admin-password" />
            </div>
            <Button type="submit" disabled={loading} className="w-full bg-brand hover:bg-brand-hover" data-testid="admin-login-btn">
              {loading ? 'Connexion...' : 'Se connecter'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

// ---------- Users table ----------
const USER_LABELS = { candidate: 'candidat', employer: 'employeur' };
const USER_CREATE_LABELS = { candidate: 'Nouveau candidat', employer: 'Nouvel employeur' };

const UsersTab = ({ userType, testid }) => {
  const { toast } = useToast();
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState('');
  const [detailFor, setDetailFor] = useState(null);
  const [editFor, setEditFor] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ email: '', password: '', first_name: '', last_name: '', phone: '', location: '' });

  const load = () => adminService.listUsers(userType, search).then(setRows).catch((e) => toast({ title: 'Erreur', description: e.message, variant: 'destructive' }));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [userType]);

  const toggle = async (id) => { const r = await adminService.toggleUser(id); setRows((p) => p.map((u) => u.id === id ? { ...u, is_active: r.is_active } : u)); };
  const remove = async (id) => { if (!window.confirm('Supprimer ce compte ?')) return; await adminService.deleteUser(id); setRows((p) => p.filter((u) => u.id !== id)); toast({ title: 'Compte supprimé' }); };

  const saveEdit = async () => {
    try {
      await adminService.updateUser(editFor.id, {
        first_name: editFor.first_name, last_name: editFor.last_name,
        phone: editFor.phone, location: editFor.location, bio: editFor.bio,
      });
      toast({ title: 'Compte mis à jour' });
      setEditFor(null); load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const createUser = async () => {
    if (!form.email.trim() || !form.password.trim()) { toast({ title: 'Email et mot de passe requis', variant: 'destructive' }); return; }
    try {
      const payload = { ...form, user_type: userType };
      // Reuse registration endpoint via api directly (already available for both types).
      const { api } = await import('../services/api').then((m) => ({ api: m.default }));
      await api.post('/auth/register', payload);
      toast({ title: 'Compte créé' });
      setCreateOpen(false); setForm({ email: '', password: '', first_name: '', last_name: '', phone: '', location: '' });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const detailFields = [
    { key: 'first_name', label: 'Prénom' }, { key: 'last_name', label: 'Nom' },
    { key: 'email', label: 'Email' }, { key: 'phone', label: 'Téléphone' },
    { key: 'location', label: 'Localisation' }, { key: 'bio', label: 'Bio' },
    { key: 'skills', label: 'Compétences' }, { key: 'experience_years', label: "Années d'exp." },
    { key: 'user_type', label: 'Type' }, { key: 'is_active', label: 'Actif' },
    { key: 'signup_source', label: 'Provenance' }, { key: 'utm_campaign', label: 'Campagne' },
    { key: 'created_at', label: 'Créé le' },
  ];

  return (
    <div data-testid={testid}>
      <AdminListHeader
        count={rows.length}
        label={USER_LABELS[userType] || 'compte'}
        onCreate={() => setCreateOpen(true)}
        createLabel={USER_CREATE_LABELS[userType] || 'Nouveau'}
        createTestId={`${testid}-create`}
      >
        <div className="flex gap-2">
          <Input placeholder="Rechercher par nom ou email..." value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load()} data-testid={`${testid}-search`} className="w-64" />
          <Button variant="outline" onClick={load} size="sm"><Search className="h-4 w-4 mr-1" />Rechercher</Button>
        </div>
      </AdminListHeader>
      <Card className="rounded-2xl">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead><TableHead>Email</TableHead><TableHead>Provenance</TableHead><TableHead>Statut</TableHead><TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow><TableCell colSpan={5} className="text-center text-slate-400 py-8">Aucun compte</TableCell></TableRow>
            ) : rows.map((u) => (
              <TableRow key={u.id} data-testid={`${testid}-row-${u.id}`}>
                <TableCell className="font-medium">
                  <DetailLinkCell onOpen={() => setDetailFor(u)} testId={`${testid}-detail-${u.id}`}>
                    {u.first_name} {u.last_name}
                  </DetailLinkCell>
                </TableCell>
                <TableCell className="text-slate-500">{u.email}</TableCell>
                <TableCell data-testid={`${testid}-source-${u.id}`}>
                  {u.signup_source
                    ? <Badge className="bg-slate-100 text-slate-600" title={u.utm_campaign ? `Campagne : ${u.utm_campaign}` : (u.signup_referrer || '')}>{u.signup_source}</Badge>
                    : <span className="text-slate-300 text-xs">—</span>}
                </TableCell>
                <TableCell>
                  {u.is_active ? <Badge className="bg-emerald-100 text-emerald-700">Actif</Badge> : <Badge className="bg-slate-200 text-slate-600">Désactivé</Badge>}
                </TableCell>
                <TableCell className="text-right space-x-1">
                  <Button variant="ghost" size="sm" onClick={() => setEditFor({ ...u })} title="Modifier" data-testid={`${testid}-edit-${u.id}`}>
                    <Pencil className="h-4 w-4 text-slate-600" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => toggle(u.id)} title={u.is_active ? 'Désactiver' : 'Activer'} data-testid={`${testid}-toggle-${u.id}`}>
                    {u.is_active ? <Ban className="h-4 w-4 text-amber-600" /> : <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
                  </Button>
                  <Button variant="ghost" size="sm" className="text-rose-600" onClick={() => remove(u.id)} data-testid={`${testid}-delete-${u.id}`}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <DetailDialog open={!!detailFor} onOpenChange={(o) => !o && setDetailFor(null)} title={`Compte — ${detailFor?.first_name || ''} ${detailFor?.last_name || ''}`} record={detailFor} fields={detailFields} />

      {/* Edit user dialog */}
      <Dialog open={!!editFor} onOpenChange={(o) => !o && setEditFor(null)}>
        <DialogContent className="sm:max-w-lg" data-testid={`${testid}-edit-dialog`}>
          <DialogHeader><DialogTitle className="font-heading">Modifier le compte</DialogTitle></DialogHeader>
          {editFor && (
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Prénom</Label><Input value={editFor.first_name || ''} onChange={(e) => setEditFor({ ...editFor, first_name: e.target.value })} /></div>
              <div><Label>Nom</Label><Input value={editFor.last_name || ''} onChange={(e) => setEditFor({ ...editFor, last_name: e.target.value })} /></div>
              <div className="col-span-2"><Label>Téléphone</Label><Input value={editFor.phone || ''} onChange={(e) => setEditFor({ ...editFor, phone: e.target.value })} /></div>
              <div className="col-span-2"><Label>Localisation</Label><Input value={editFor.location || ''} onChange={(e) => setEditFor({ ...editFor, location: e.target.value })} /></div>
              <div className="col-span-2"><Label>Bio</Label><Textarea rows={3} value={editFor.bio || ''} onChange={(e) => setEditFor({ ...editFor, bio: e.target.value })} /></div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditFor(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={saveEdit} data-testid={`${testid}-edit-save`}>Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create user dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-lg" data-testid={`${testid}-create-dialog`}>
          <DialogHeader><DialogTitle className="font-heading">{USER_CREATE_LABELS[userType]}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Prénom</Label><Input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></div>
            <div><Label>Nom</Label><Input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></div>
            <div className="col-span-2"><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div className="col-span-2"><Label>Mot de passe</Label><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
            <div><Label>Téléphone</Label><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
            <div><Label>Localisation</Label><Input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={createUser} data-testid={`${testid}-create-submit`}>Créer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

// ---------- Partners ----------
const PACKS = [5, 10, 20, 50, 100, 200];

const PartnersTab = () => {
  const { toast } = useToast();
  const [rows, setRows] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [configFor, setConfigFor] = useState(null);
  const [importFor, setImportFor] = useState(null);
  const [importXml, setImportXml] = useState('');
  const [rechargeFor, setRechargeFor] = useState(null);
  const [detailFor, setDetailFor] = useState(null);
  const [search, setSearch] = useState('');
  const [form, setForm] = useState({ email: '', password: '', first_name: '', company_name: '', billing_mode: 'per_click', default_cpc: '0.30', posting_price: '2.00', xml_feed_url: '' });
  const [cfg, setCfg] = useState({ billing_mode: 'per_click', default_cpc: '', posting_price: '', xml_feed_url: '', add_pack: '', add_balance: '' });

  const load = () => adminService.listPartners(search).then(setRows).catch((e) => toast({ title: 'Erreur', description: e.message, variant: 'destructive' }));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const partnerDetailFields = [
    { key: 'profile.company_name', label: 'Société' },
    { key: 'first_name', label: 'Contact' },
    { key: 'email', label: 'Email' },
    { key: 'profile.billing_mode', label: 'Facturation', render: (v) => v === 'per_click' ? 'Au clic' : "À l'annonce" },
    { key: 'profile.default_cpc', label: 'CPC (€/clic)' },
    { key: 'profile.posting_price', label: 'Prix / annonce (€)' },
    { key: 'profile.balance', label: 'Solde (€)' },
    { key: 'profile.postings_remaining', label: 'Annonces restantes' },
    { key: 'profile.total_clicks', label: 'Clics totaux' },
    { key: 'profile.total_spent', label: 'Dépensé total (€)' },
    { key: 'profile.xml_feed_url', label: 'Flux XML' },
    { key: 'is_active', label: 'Actif' },
    { key: 'created_at', label: 'Créé le' },
  ];

  const create = async () => {
    try {
      await adminService.createPartner({
        email: form.email, password: form.password, first_name: form.first_name,
        company_name: form.company_name, billing_mode: form.billing_mode,
        default_cpc: parseFloat(form.default_cpc) || 0, posting_price: parseFloat(form.posting_price) || 0,
        xml_feed_url: form.xml_feed_url || null,
      });
      toast({ title: 'Partenaire créé' });
      setShowCreate(false); load();
    } catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
  };

  const openConfig = (p) => {
    setConfigFor(p);
    setCfg({ billing_mode: p.profile.billing_mode, default_cpc: String(p.profile.default_cpc), posting_price: String(p.profile.posting_price), xml_feed_url: p.profile.xml_feed_url || '', add_pack: '', add_balance: '' });
  };

  const saveConfig = async () => {
    try {
      const payload = {
        billing_mode: cfg.billing_mode,
        default_cpc: cfg.default_cpc === '' ? undefined : parseFloat(cfg.default_cpc),
        posting_price: cfg.posting_price === '' ? undefined : parseFloat(cfg.posting_price),
        xml_feed_url: cfg.xml_feed_url || undefined,
        add_pack: cfg.add_pack ? parseInt(cfg.add_pack) : undefined,
        add_balance: cfg.add_balance ? parseFloat(cfg.add_balance) : undefined,
      };
      await adminService.configPartner(configFor.id, payload);
      toast({ title: 'Configuration enregistrée' });
      setConfigFor(null); load();
    } catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
  };

  const runImport = async () => {
    try {
      const res = await adminService.importXml(importFor.id, importXml);
      toast({ title: 'Import terminé', description: `${res.imported} importée(s), ${res.updated} mise(s) à jour, ${res.skipped_no_credit} sans crédit` });
      setImportFor(null); setImportXml(''); load();
    } catch (e) { toast({ title: 'Erreur', description: e.message, variant: 'destructive' }); }
  };

  return (
    <div data-testid="admin-partners-tab">
      <AdminListHeader
        count={rows.length}
        label="partenaire"
        onCreate={() => setShowCreate(true)}
        createLabel="Nouveau partenaire"
        createTestId="admin-create-partner-btn"
      >
        <div className="flex gap-2">
          <Input placeholder="Société, nom, email..." value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load()} data-testid="admin-partners-search" className="w-64" />
          <Button variant="outline" size="sm" onClick={load} data-testid="admin-partners-search-btn"><Search className="h-4 w-4 mr-1" />Rechercher</Button>
        </div>
      </AdminListHeader>
      <Card className="rounded-2xl">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Entreprise</TableHead><TableHead>Email</TableHead><TableHead>Facturation</TableHead>
              <TableHead>CPC / Prix</TableHead><TableHead>Crédits</TableHead><TableHead>Clics</TableHead><TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow><TableCell colSpan={7} className="text-center text-slate-400 py-8">Aucun partenaire</TableCell></TableRow>
            ) : rows.map((p) => (
              <TableRow key={p.id} data-testid={`admin-partner-row-${p.id}`}>
                <TableCell className="font-medium">
                  <DetailLinkCell onOpen={() => setDetailFor(p)} testId={`admin-partner-detail-${p.id}`}>
                    {p.profile.company_name}
                  </DetailLinkCell>
                </TableCell>
                <TableCell className="text-slate-500">{p.email}</TableCell>
                <TableCell><Badge className="bg-brand/10 text-brand">{p.profile.billing_mode === 'per_click' ? 'Au clic' : 'À l\'annonce'}</Badge></TableCell>
                <TableCell>{p.profile.billing_mode === 'per_click' ? `${p.profile.default_cpc.toFixed(2)} €/clic` : `${p.profile.posting_price.toFixed(2)} €/annonce`}</TableCell>
                <TableCell>{p.profile.billing_mode === 'per_click' ? `${p.profile.balance.toFixed(2)} €` : `${p.profile.postings_remaining} annonces`}</TableCell>
                <TableCell>{p.profile.total_clicks}</TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="sm" onClick={() => openConfig(p)} title="Modifier / configurer" data-testid={`admin-partner-edit-${p.id}`}><Pencil className="h-4 w-4 text-slate-600" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => setRechargeFor(p)} title="Recharger le solde" className="text-emerald-600" data-testid={`admin-partner-recharge-${p.id}`}><CreditCard className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => setImportFor(p)} title="Importer le flux XML" data-testid={`admin-partner-import-${p.id}`}><Download className="h-4 w-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <DetailDialog open={!!detailFor} onOpenChange={(o) => !o && setDetailFor(null)} title={`Partenaire — ${detailFor?.profile?.company_name || ''}`} record={detailFor} fields={partnerDetailFields} />

      {/* Create partner dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="sm:max-w-lg" data-testid="admin-create-partner-dialog">
          <DialogHeader><DialogTitle>Créer un partenaire</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Nom du contact</Label><Input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} data-testid="partner-firstname" /></div>
            <div><Label>Entreprise</Label><Input value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} data-testid="partner-company" /></div>
            <div><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="partner-email" /></div>
            <div><Label>Mot de passe</Label><Input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="partner-password" /></div>
            <div>
              <Label>Mode de facturation</Label>
              <Select value={form.billing_mode} onValueChange={(v) => setForm({ ...form, billing_mode: v })}>
                <SelectTrigger data-testid="partner-billing-mode"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="per_click">Au clic</SelectItem><SelectItem value="per_posting">À l'annonce</SelectItem></SelectContent>
              </Select>
            </div>
            <div><Label>CPC (€/clic)</Label><Input type="number" step="0.01" value={form.default_cpc} onChange={(e) => setForm({ ...form, default_cpc: e.target.value })} data-testid="partner-cpc" /></div>
            <div><Label>Prix / annonce (€)</Label><Input type="number" step="0.01" value={form.posting_price} onChange={(e) => setForm({ ...form, posting_price: e.target.value })} /></div>
            <div className="col-span-2"><Label>URL du flux XML (optionnel)</Label><Input value={form.xml_feed_url} onChange={(e) => setForm({ ...form, xml_feed_url: e.target.value })} placeholder="https://..." data-testid="partner-xml" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={create} data-testid="partner-create-submit">Créer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Config partner dialog */}
      <Dialog open={!!configFor} onOpenChange={(o) => !o && setConfigFor(null)}>
        <DialogContent className="sm:max-w-lg" data-testid="admin-config-partner-dialog">
          <DialogHeader><DialogTitle>Configurer — {configFor?.profile?.company_name}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Mode de facturation</Label>
              <Select value={cfg.billing_mode} onValueChange={(v) => setCfg({ ...cfg, billing_mode: v })}>
                <SelectTrigger data-testid="config-billing-mode"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="per_click">Au clic</SelectItem><SelectItem value="per_posting">À l'annonce</SelectItem></SelectContent>
              </Select>
            </div>
            <div><Label>CPC (€/clic)</Label><Input type="number" step="0.01" value={cfg.default_cpc} onChange={(e) => setCfg({ ...cfg, default_cpc: e.target.value })} data-testid="config-cpc" /></div>
            <div><Label>Prix / annonce (€)</Label><Input type="number" step="0.01" value={cfg.posting_price} onChange={(e) => setCfg({ ...cfg, posting_price: e.target.value })} data-testid="config-posting-price" /></div>
            <div>
              <Label>Ajouter un pack d'annonces</Label>
              <Select value={cfg.add_pack} onValueChange={(v) => setCfg({ ...cfg, add_pack: v })}>
                <SelectTrigger data-testid="config-add-pack"><SelectValue placeholder="Choisir un pack" /></SelectTrigger>
                <SelectContent>{PACKS.map((n) => <SelectItem key={n} value={String(n)}>{n} annonces</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Ajouter du crédit (€)</Label><Input type="number" step="1" value={cfg.add_balance} onChange={(e) => setCfg({ ...cfg, add_balance: e.target.value })} data-testid="config-add-balance" /></div>
            <div className="col-span-2"><Label>URL du flux XML</Label><Input value={cfg.xml_feed_url} onChange={(e) => setCfg({ ...cfg, xml_feed_url: e.target.value })} data-testid="config-xml" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfigFor(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={saveConfig} data-testid="config-save">Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Import XML dialog */}
      <Dialog open={!!importFor} onOpenChange={(o) => { if (!o) { setImportFor(null); setImportXml(''); } }}>
        <DialogContent className="sm:max-w-2xl" data-testid="admin-import-xml-dialog">
          <DialogHeader><DialogTitle>Importer le flux XML — {importFor?.profile?.company_name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">
              Collez le contenu XML ci-dessous, ou laissez vide pour récupérer automatiquement le flux depuis l'URL configurée
              {importFor?.profile?.xml_feed_url ? ` (${importFor.profile.xml_feed_url})` : ' (aucune URL configurée)'}.
            </p>
            <div>
              <Label>Contenu XML (optionnel)</Label>
              <Textarea
                value={importXml}
                onChange={(e) => setImportXml(e.target.value)}
                rows={10}
                placeholder={'<jobs>\n  <job>\n    <title>Développeur React</title>\n    <company>Ma Société</company>\n    <location>Paris</location>\n    <description>...</description>\n    <url>https://...</url>\n    <cpc>0.40</cpc>\n    <job_type>CDI</job_type>\n    <reference>ref-123</reference>\n  </job>\n</jobs>'}
                className="font-mono text-xs"
                data-testid="import-xml-textarea"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setImportFor(null); setImportXml(''); }}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={runImport} data-testid="import-xml-submit">
              <Download className="h-4 w-4 mr-1" />Lancer l'import
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Admin recharge dialog (Stripe) */}
      <RechargeDialog
        open={!!rechargeFor}
        onOpenChange={(o) => { if (!o) { setRechargeFor(null); load(); } }}
        partnerId={rechargeFor?.id}
        companyName={rechargeFor?.profile?.company_name}
        billingMode={rechargeFor?.profile?.billing_mode}
        postingPrice={rechargeFor?.profile?.posting_price}
      />
    </div>
  );
};

// ---------- Jobs ----------
const JobsTab = () => {
  const { toast } = useToast();
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState({ search: '', location: '' });
  const [detailFor, setDetailFor] = useState(null);
  const [editFor, setEditFor] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ title: '', company_id: '', location: '', job_type: 'cdi', description: '', salary_min: '', salary_max: '' });
  const [companies, setCompanies] = useState([]);

  const load = () => adminService.searchJobs({ search: q.search || undefined, location: q.location || undefined }).then(setRows).catch((e) => toast({ title: 'Erreur', description: e.message, variant: 'destructive' }));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    // For the create dialog: list companies so admin can pick one
    (async () => {
      try {
        const api = (await import('../services/api')).default;
        const list = (await api.get('/companies')).data;
        setCompanies(list || []);
      } catch { /* silent */ }
    })();
  }, []);

  const toggle = async (id) => { const r = await adminService.toggleJob(id); setRows((p) => p.map((j) => j.id === id ? { ...j, is_active: r.is_active } : j)); toast({ title: r.is_active ? 'Diffusion réactivée' : 'Diffusion arrêtée' }); };
  const remove = async (id) => { if (!window.confirm('Supprimer cette offre ?')) return; await adminService.deleteJob(id); setRows((p) => p.filter((j) => j.id !== id)); toast({ title: 'Offre supprimée' }); };

  const saveEdit = async () => {
    try {
      await adminService.updateJob(editFor.id, {
        title: editFor.title, location: editFor.location, job_type: editFor.job_type,
        description: editFor.description,
        salary_min: editFor.salary_min === '' || editFor.salary_min == null ? null : parseFloat(editFor.salary_min),
        salary_max: editFor.salary_max === '' || editFor.salary_max == null ? null : parseFloat(editFor.salary_max),
      });
      toast({ title: 'Offre mise à jour' });
      setEditFor(null); load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const createJob = async () => {
    if (!form.title.trim() || !form.company_id) { toast({ title: 'Titre et entreprise requis', variant: 'destructive' }); return; }
    try {
      const api = (await import('../services/api')).default;
      await api.post('/jobs', {
        title: form.title, description: form.description, company_id: form.company_id,
        location: form.location, job_type: form.job_type,
        salary_min: form.salary_min ? parseFloat(form.salary_min) : null,
        salary_max: form.salary_max ? parseFloat(form.salary_max) : null,
      });
      toast({ title: 'Offre créée' });
      setCreateOpen(false); setForm({ title: '', company_id: '', location: '', job_type: 'cdi', description: '', salary_min: '', salary_max: '' });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const jobDetailFields = [
    { key: 'title', label: 'Titre' }, { key: 'location', label: 'Localisation' },
    { key: 'job_type', label: 'Type' }, { key: 'salary_min', label: 'Salaire min (€)' },
    { key: 'salary_max', label: 'Salaire max (€)' }, { key: 'description', label: 'Description' },
    { key: 'company', label: 'Entreprise', render: (v) => v?.name || '—' },
    { key: 'views_count', label: 'Vues' }, { key: 'applications_count', label: 'Candidatures' },
    { key: 'is_active', label: 'En ligne' }, { key: 'partner_source', label: 'Source partenaire' },
    { key: 'external_apply_url', label: 'URL externe' }, { key: 'created_at', label: 'Créée le' },
  ];

  return (
    <div data-testid="admin-jobs-tab">
      <AdminListHeader
        count={rows.length}
        label="offre"
        onCreate={() => setCreateOpen(true)}
        createLabel="Nouvelle offre"
        createTestId="admin-create-job-btn"
      >
        <div className="flex gap-2 flex-wrap">
          <Input placeholder="Titre..." value={q.search} onChange={(e) => setQ({ ...q, search: e.target.value })} className="w-44" data-testid="admin-jobs-search" />
          <Input placeholder="Localisation..." value={q.location} onChange={(e) => setQ({ ...q, location: e.target.value })} className="w-40" data-testid="admin-jobs-location" />
          <Button variant="outline" size="sm" onClick={load} data-testid="admin-jobs-search-btn"><Search className="h-4 w-4 mr-1" />Rechercher</Button>
        </div>
      </AdminListHeader>
      <Card className="rounded-2xl">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Titre</TableHead><TableHead>Localisation</TableHead><TableHead>Type</TableHead>
              <TableHead>Diffusion</TableHead><TableHead>Vues</TableHead><TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow><TableCell colSpan={6} className="text-center text-slate-400 py-8">Aucune offre</TableCell></TableRow>
            ) : rows.map((j) => (
              <TableRow key={j.id} data-testid={`admin-job-row-${j.id}`}>
                <TableCell className="font-medium">
                  <DetailLinkCell onOpen={() => setDetailFor(j)} testId={`admin-job-detail-${j.id}`}>{j.title}</DetailLinkCell>
                </TableCell>
                <TableCell className="text-slate-500">{j.location}</TableCell>
                <TableCell>{j.job_type}</TableCell>
                <TableCell>{j.is_active ? <Badge className="bg-emerald-100 text-emerald-700">En ligne</Badge> : <Badge className="bg-slate-200 text-slate-600">Stoppée</Badge>}</TableCell>
                <TableCell>{j.views_count}</TableCell>
                <TableCell className="text-right space-x-1">
                  <Button variant="ghost" size="sm" onClick={() => setEditFor({ ...j })} title="Modifier" data-testid={`admin-job-edit-${j.id}`}><Pencil className="h-4 w-4 text-slate-600" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => toggle(j.id)} title={j.is_active ? 'Arrêter la diffusion' : 'Réactiver'} data-testid={`admin-job-toggle-${j.id}`}>
                    <Power className={`h-4 w-4 ${j.is_active ? 'text-amber-600' : 'text-emerald-600'}`} />
                  </Button>
                  <Button variant="ghost" size="sm" className="text-rose-600" onClick={() => remove(j.id)} data-testid={`admin-job-delete-${j.id}`}><Trash2 className="h-4 w-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <DetailDialog open={!!detailFor} onOpenChange={(o) => !o && setDetailFor(null)} title={`Offre — ${detailFor?.title || ''}`} record={detailFor} fields={jobDetailFields} />

      {/* Edit job dialog */}
      <Dialog open={!!editFor} onOpenChange={(o) => !o && setEditFor(null)}>
        <DialogContent className="sm:max-w-lg" data-testid="admin-job-edit-dialog">
          <DialogHeader><DialogTitle className="font-heading">Modifier l&apos;offre</DialogTitle></DialogHeader>
          {editFor && (
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2"><Label>Titre</Label><Input value={editFor.title || ''} onChange={(e) => setEditFor({ ...editFor, title: e.target.value })} /></div>
              <div><Label>Localisation</Label><Input value={editFor.location || ''} onChange={(e) => setEditFor({ ...editFor, location: e.target.value })} /></div>
              <div>
                <Label>Type</Label>
                <Select value={editFor.job_type || 'cdi'} onValueChange={(v) => setEditFor({ ...editFor, job_type: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="cdi">CDI</SelectItem><SelectItem value="cdd">CDD</SelectItem>
                    <SelectItem value="stage">Stage</SelectItem><SelectItem value="freelance">Freelance</SelectItem>
                    <SelectItem value="interim">Intérim</SelectItem><SelectItem value="alternance">Alternance</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div><Label>Salaire min (€)</Label><Input type="number" value={editFor.salary_min ?? ''} onChange={(e) => setEditFor({ ...editFor, salary_min: e.target.value })} /></div>
              <div><Label>Salaire max (€)</Label><Input type="number" value={editFor.salary_max ?? ''} onChange={(e) => setEditFor({ ...editFor, salary_max: e.target.value })} /></div>
              <div className="col-span-2"><Label>Description</Label><Textarea rows={5} value={editFor.description || ''} onChange={(e) => setEditFor({ ...editFor, description: e.target.value })} /></div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditFor(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={saveEdit} data-testid="admin-job-edit-save">Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create job dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-lg" data-testid="admin-job-create-dialog">
          <DialogHeader><DialogTitle className="font-heading">Nouvelle offre</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2"><Label>Titre</Label><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            <div className="col-span-2">
              <Label>Entreprise</Label>
              <Select value={form.company_id} onValueChange={(v) => setForm({ ...form, company_id: v })}>
                <SelectTrigger data-testid="admin-job-create-company"><SelectValue placeholder="Choisir une entreprise" /></SelectTrigger>
                <SelectContent>{companies.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Localisation</Label><Input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div>
            <div>
              <Label>Type</Label>
              <Select value={form.job_type} onValueChange={(v) => setForm({ ...form, job_type: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="cdi">CDI</SelectItem><SelectItem value="cdd">CDD</SelectItem>
                  <SelectItem value="stage">Stage</SelectItem><SelectItem value="freelance">Freelance</SelectItem>
                  <SelectItem value="interim">Intérim</SelectItem><SelectItem value="alternance">Alternance</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div><Label>Salaire min (€)</Label><Input type="number" value={form.salary_min} onChange={(e) => setForm({ ...form, salary_min: e.target.value })} /></div>
            <div><Label>Salaire max (€)</Label><Input type="number" value={form.salary_max} onChange={(e) => setForm({ ...form, salary_max: e.target.value })} /></div>
            <div className="col-span-2"><Label>Description</Label><Textarea rows={5} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={createJob} data-testid="admin-job-create-save">Créer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

// ---------- Flux XML campaigns tab ----------
const FeedsTab = () => {
  const { toast } = useToast();
  const [rows, setRows] = useState([]);
  const [partners, setPartners] = useState([]);
  const [open, setOpen] = useState(false);
  const [detailFor, setDetailFor] = useState(null);
  const [editFor, setEditFor] = useState(null);
  const [form, setForm] = useState({ source_name: '', url: '', billing_mode: 'per_click', cpc: '0.40', pack_price: '2.00', assign: 'new', partner_id: '', new_partner_company: '', new_partner_email: '' });
  const [saving, setSaving] = useState(false);

  const load = () => {
    adminService.listFeeds().then(setRows).catch(() => {});
    adminService.listPartners().then(setPartners).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  const set = (p) => setForm((f) => ({ ...f, ...p }));

  const save = async () => {
    if (!form.source_name.trim() || !form.url.trim()) { toast({ title: 'Nom et URL requis', variant: 'destructive' }); return; }
    setSaving(true);
    try {
      const payload = {
        source_name: form.source_name, url: form.url, billing_mode: form.billing_mode,
        cpc: parseFloat(form.cpc) || 0, pack_price: parseFloat(form.pack_price) || 0,
      };
      if (form.assign === 'existing') {
        if (!form.partner_id) { toast({ title: 'Sélectionnez un partenaire', variant: 'destructive' }); setSaving(false); return; }
        payload.partner_id = form.partner_id;
      } else {
        if (!form.new_partner_company.trim()) { toast({ title: 'Nom du nouveau partenaire requis', variant: 'destructive' }); setSaving(false); return; }
        payload.new_partner_company = form.new_partner_company;
        payload.new_partner_email = form.new_partner_email || null;
      }
      await adminService.createFeed(payload);
      toast({ title: 'Flux ajouté' });
      setOpen(false); load();
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setSaving(false); }
  };

  const runImport = async (f) => {
    try {
      const r = await adminService.importFeed(f.id);
      toast({ title: 'Import terminé', description: `${r.imported} importée(s), ${r.updated} mise(s) à jour, ${r.skipped_no_credit} sans crédit` });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };
  const remove = async (f) => { if (!window.confirm('Supprimer ce flux ?')) return; await adminService.deleteFeed(f.id); load(); };

  const saveEdit = async () => {
    try {
      await adminService.updateFeed(editFor.id, {
        source_name: editFor.source_name, url: editFor.url, billing_mode: editFor.billing_mode,
        cpc: editFor.cpc == null || editFor.cpc === '' ? null : parseFloat(editFor.cpc),
        pack_price: editFor.pack_price == null || editFor.pack_price === '' ? null : parseFloat(editFor.pack_price),
      });
      toast({ title: 'Flux mis à jour' });
      setEditFor(null); load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const feedDetailFields = [
    { key: 'source_name', label: 'Source' }, { key: 'company_name', label: 'Partenaire' },
    { key: 'url', label: 'URL' },
    { key: 'billing_mode', label: 'Facturation', render: (v) => v === 'per_click' ? 'Au clic' : "À l'annonce" },
    { key: 'cpc', label: 'CPC (€)' }, { key: 'pack_price', label: 'Prix pack (€)' },
    { key: 'last_import_at', label: 'Dernier import' },
    { key: 'last_result', label: 'Dernier résultat', render: (v) => v ? `${v.imported} importée(s), ${v.updated} maj, ${v.skipped_no_credit} sans crédit` : '—' },
    { key: 'created_at', label: 'Créé le' },
  ];

  return (
    <div data-testid="admin-feeds">
      <AdminListHeader
        count={rows.length}
        label="flux"
        onCreate={() => setOpen(true)}
        createLabel="Nouveau flux"
        createTestId="new-feed-btn"
      />
      <p className="text-xs text-slate-500 mb-3">Campagnes de diffusion via flux XML — affectez à un partenaire existant ou créez-en un (sans login).</p>
      <Card className="rounded-2xl">
        <Table>
          <TableHeader><TableRow><TableHead>Source</TableHead><TableHead>Partenaire</TableHead><TableHead>Facturation</TableHead><TableHead>CPC / Pack</TableHead><TableHead>Dernier import</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow><TableCell colSpan={6} className="text-center text-slate-400 py-8">Aucun flux XML configuré</TableCell></TableRow>
            ) : rows.map((f) => (
              <TableRow key={f.id} data-testid={`feed-row-${f.id}`}>
                <TableCell className="font-medium">
                  <DetailLinkCell onOpen={() => setDetailFor(f)} testId={`feed-detail-${f.id}`}>{f.source_name}</DetailLinkCell>
                </TableCell>
                <TableCell>{f.company_name}</TableCell>
                <TableCell><Badge className="bg-brand/10 text-brand">{f.billing_mode === 'per_click' ? 'Au clic' : "À l'annonce"}</Badge></TableCell>
                <TableCell>{f.billing_mode === 'per_click' ? `${(f.cpc ?? 0).toFixed(2)} €` : `${(f.pack_price ?? 0).toFixed(2)} €`}</TableCell>
                <TableCell className="text-xs text-slate-500">{f.last_result ? `${f.last_result.imported} imp. / ${f.last_result.updated} maj` : '—'}</TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="sm" onClick={() => setEditFor({ ...f })} title="Modifier" data-testid={`feed-edit-${f.id}`}><Pencil className="h-4 w-4 text-slate-600" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => runImport(f)} title="Importer maintenant" data-testid={`feed-import-${f.id}`}><RefreshCw className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" className="text-red-500" onClick={() => remove(f)} data-testid={`feed-delete-${f.id}`}><Trash2 className="h-4 w-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <DetailDialog open={!!detailFor} onOpenChange={(o) => !o && setDetailFor(null)} title={`Flux — ${detailFor?.source_name || ''}`} record={detailFor} fields={feedDetailFields} />

      {/* Edit feed dialog */}
      <Dialog open={!!editFor} onOpenChange={(o) => !o && setEditFor(null)}>
        <DialogContent className="sm:max-w-lg" data-testid="feed-edit-dialog">
          <DialogHeader><DialogTitle className="font-heading">Modifier le flux</DialogTitle></DialogHeader>
          {editFor && (
            <div className="space-y-3">
              <div><Label>Nom de la source</Label><Input value={editFor.source_name || ''} onChange={(e) => setEditFor({ ...editFor, source_name: e.target.value })} /></div>
              <div><Label>URL du flux XML</Label><Input value={editFor.url || ''} onChange={(e) => setEditFor({ ...editFor, url: e.target.value })} /></div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Facturation</Label>
                  <select value={editFor.billing_mode} onChange={(e) => setEditFor({ ...editFor, billing_mode: e.target.value })} className="w-full h-10 border border-slate-200 rounded-md px-3 text-sm mt-1">
                    <option value="per_click">Au clic (CPC)</option>
                    <option value="per_posting">Prix du pack</option>
                  </select>
                </div>
                {editFor.billing_mode === 'per_click'
                  ? <div><Label>CPC (€)</Label><Input type="number" step="0.01" value={editFor.cpc ?? ''} onChange={(e) => setEditFor({ ...editFor, cpc: e.target.value })} /></div>
                  : <div><Label>Prix pack (€/annonce)</Label><Input type="number" step="0.01" value={editFor.pack_price ?? ''} onChange={(e) => setEditFor({ ...editFor, pack_price: e.target.value })} /></div>}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditFor(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={saveEdit} data-testid="feed-edit-save">Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg" data-testid="feed-dialog">
          <DialogHeader><DialogTitle className="font-heading flex items-center gap-2"><Rss className="h-5 w-5 text-brand" />Nouveau flux XML</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nom de la source</Label><Input value={form.source_name} onChange={(e) => set({ source_name: e.target.value })} data-testid="feed-source-name" /></div>
            <div><Label>URL du flux XML</Label><Input value={form.url} onChange={(e) => set({ url: e.target.value })} placeholder="https://..." data-testid="feed-url" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Facturation</Label>
                <select value={form.billing_mode} onChange={(e) => set({ billing_mode: e.target.value })} className="w-full h-10 border border-slate-200 rounded-md px-3 text-sm mt-1" data-testid="feed-billing-mode">
                  <option value="per_click">Au clic (CPC)</option>
                  <option value="per_posting">Prix du pack</option>
                </select>
              </div>
              {form.billing_mode === 'per_click'
                ? <div><Label>CPC (€)</Label><Input type="number" step="0.01" value={form.cpc} onChange={(e) => set({ cpc: e.target.value })} data-testid="feed-cpc" /></div>
                : <div><Label>Prix pack (€/annonce)</Label><Input type="number" step="0.01" value={form.pack_price} onChange={(e) => set({ pack_price: e.target.value })} data-testid="feed-pack-price" /></div>}
            </div>
            <div>
              <Label>Affecter à</Label>
              <select value={form.assign} onChange={(e) => set({ assign: e.target.value })} className="w-full h-10 border border-slate-200 rounded-md px-3 text-sm mt-1" data-testid="feed-assign">
                <option value="new">Nouveau partenaire (sans login)</option>
                <option value="existing">Partenaire existant</option>
              </select>
            </div>
            {form.assign === 'existing' ? (
              <select value={form.partner_id} onChange={(e) => set({ partner_id: e.target.value })} className="w-full h-10 border border-slate-200 rounded-md px-3 text-sm" data-testid="feed-partner-select">
                <option value="">— Choisir un partenaire —</option>
                {partners.map((p) => <option key={p.id} value={p.id}>{p.profile?.company_name || p.email}</option>)}
              </select>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Nom du partenaire</Label><Input value={form.new_partner_company} onChange={(e) => set({ new_partner_company: e.target.value })} data-testid="feed-new-company" /></div>
                <div><Label>Email (optionnel)</Label><Input value={form.new_partner_email} onChange={(e) => set({ new_partner_email: e.target.value })} data-testid="feed-new-email" /></div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={save} disabled={saving} data-testid="feed-save">{saving ? '...' : 'Ajouter'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

// ---------- Alerts management tab ----------
const AlertsTab = () => {
  const { toast } = useToast();
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState('');
  const [active, setActive] = useState('');

  const load = () => adminService.listAlerts({ search: search || undefined, active: active || undefined }).then(setRows).catch(() => {});
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [active]);

  const toggle = async (a) => { await adminService.toggleAlert(a.id); load(); };
  const remove = async (a) => { if (!window.confirm('Supprimer cette alerte ?')) return; await adminService.deleteAlert(a.id); load(); toast({ title: 'Alerte supprimée' }); };

  return (
    <div data-testid="admin-alerts">
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load()} placeholder="Rechercher (nom, terme, lieu)" className="pl-9" data-testid="alerts-search" />
        </div>
        <select value={active} onChange={(e) => setActive(e.target.value)} className="h-10 border border-slate-200 rounded-md px-3 text-sm" data-testid="alerts-filter-active">
          <option value="">Toutes</option>
          <option value="true">Actives</option>
          <option value="false">Désactivées</option>
        </select>
        <Button variant="outline" onClick={load} data-testid="alerts-search-btn">Rechercher</Button>
      </div>
      <Card className="rounded-2xl">
        <Table>
          <TableHeader><TableRow><TableHead>Alerte</TableHead><TableHead>Email</TableHead><TableHead>Mode</TableHead><TableHead>Origine</TableHead><TableHead>Dernière consultation</TableHead><TableHead>Statut</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow><TableCell colSpan={7} className="text-center text-slate-400 py-8">Aucune alerte</TableCell></TableRow>
            ) : rows.map((a) => (
              <TableRow key={a.id} data-testid={`alert-row-${a.id}`}>
                <TableCell className="font-medium">{a.name}</TableCell>
                <TableCell className="text-slate-500">{a.user_email || '—'}</TableCell>
                <TableCell><Badge className="bg-slate-100 text-slate-600">{a.search_mode === 'advanced' ? 'Avancé' : 'Simple'}</Badge></TableCell>
                <TableCell className="text-xs text-slate-400">{a.origin || '—'}</TableCell>
                <TableCell className="text-xs text-slate-500">{a.last_viewed_at ? new Date(a.last_viewed_at).toLocaleDateString('fr-FR') : 'Jamais'}</TableCell>
                <TableCell>{a.is_active ? <Badge className="bg-emerald-100 text-emerald-700">Active</Badge> : <Badge className="bg-slate-200 text-slate-600">Off</Badge>}</TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="sm" onClick={() => toggle(a)} title={a.is_active ? 'Désactiver' : 'Activer'} data-testid={`alert-toggle-${a.id}`}><Power className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" className="text-red-500" onClick={() => remove(a)} data-testid={`alert-delete-${a.id}`}><Trash2 className="h-4 w-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
};

// ---------- General settings tab ----------
const SettingsTab = () => {
  const { toast } = useToast();
  const [s, setS] = useState({ pack_validity_days: 30, low_balance_threshold: 10, feed_refresh_hours: 24, recruiter_premium_price: 299 });
  const [saving, setSaving] = useState(false);

  useEffect(() => { adminService.getSettings().then(setS).catch(() => {}); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const res = await adminService.updateSettings({
        pack_validity_days: parseInt(s.pack_validity_days),
        low_balance_threshold: parseFloat(s.low_balance_threshold),
        feed_refresh_hours: parseInt(s.feed_refresh_hours),
        recruiter_premium_price: parseFloat(s.recruiter_premium_price),
      });
      setS(res);
      toast({ title: 'Paramètres enregistrés' });
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
    finally { setSaving(false); }
  };

  return (
    <div data-testid="admin-settings" className="max-w-lg">
      <Card className="rounded-2xl">
        <CardHeader><CardTitle className="font-heading text-lg flex items-center gap-2"><Settings className="h-5 w-5 text-brand" />Paramètres généraux</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label>Durée de validité par défaut d'un pack d'annonces (jours)</Label>
            <Input type="number" value={s.pack_validity_days} onChange={(e) => setS({ ...s, pack_validity_days: e.target.value })} data-testid="settings-pack-validity" />
            <p className="text-xs text-slate-400 mt-1">Appliquée aux campagnes « par pack d'annonce ». Défaut : 30 jours.</p>
          </div>
          <div>
            <Label>Seuil d'alerte « solde bas » (€)</Label>
            <Input type="number" step="1" value={s.low_balance_threshold} onChange={(e) => setS({ ...s, low_balance_threshold: e.target.value })} data-testid="settings-low-balance" />
            <p className="text-xs text-slate-400 mt-1">Un email de rechargement est envoyé au partenaire quand son solde passe sous ce seuil.</p>
          </div>
          <div>
            <Label>Fréquence de rafraîchissement automatique des flux XML (heures)</Label>
            <Input type="number" step="1" min="1" value={s.feed_refresh_hours} onChange={(e) => setS({ ...s, feed_refresh_hours: e.target.value })} data-testid="settings-feed-refresh" />
            <p className="text-xs text-slate-400 mt-1">Chaque campagne partenaire avec une URL de flux est réimportée automatiquement à cette fréquence. Défaut : 24 h.</p>
          </div>
          <div>
            <Label>Prix d'une offre Premium recruteur (€)</Label>
            <Input type="number" step="1" min="1" value={s.recruiter_premium_price} onChange={(e) => setS({ ...s, recruiter_premium_price: e.target.value })} data-testid="settings-recruiter-price" />
            <p className="text-xs text-slate-400 mt-1">Prix affiché sur la page Recruteur (« À partir de … ») et base de calcul des packs. Défaut : 299 €.</p>
          </div>
          <Button className="bg-brand hover:bg-brand-hover" onClick={save} disabled={saving} data-testid="settings-save"><Save className="h-4 w-4 mr-1" />{saving ? '...' : 'Enregistrer'}</Button>
        </CardContent>
      </Card>
    </div>
  );
};

const PendingPartnersTab = () => {
  const { toast } = useToast();
  const [list, setList] = useState([]);
  const [validating, setValidating] = useState(null);
  const [search, setSearch] = useState('');
  const [detailFor, setDetailFor] = useState(null);
  const [editFor, setEditFor] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ email: '', password: '', first_name: '', company_name: '', billing_mode: 'per_click', default_cpc: '0.30', posting_price: '2.00' });

  const load = () => adminService.listPendingPartners(search).then(setList).catch(() => {});
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const validate = async (p) => {
    setValidating(p.id);
    try {
      await adminService.validatePartner(p.id);
      toast({ title: 'Partenaire validé', description: 'Le compte est activé et un email de bienvenue a été envoyé.' });
      load();
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setValidating(null); }
  };

  const saveEdit = async () => {
    try {
      await adminService.updateUser(editFor.id, {
        first_name: editFor.first_name, last_name: editFor.last_name,
      });
      toast({ title: 'Partenaire mis à jour' });
      setEditFor(null); load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const createPending = async () => {
    if (!form.email.trim() || !form.password.trim() || !form.company_name.trim()) {
      toast({ title: 'Email, mot de passe et société requis', variant: 'destructive' }); return;
    }
    try {
      await adminService.createPartner({
        email: form.email, password: form.password, first_name: form.first_name || form.company_name,
        company_name: form.company_name, billing_mode: form.billing_mode,
        default_cpc: parseFloat(form.default_cpc) || 0, posting_price: parseFloat(form.posting_price) || 0,
      });
      // The created partner is active by default; to move it to "pending", flip is_active
      const created = (await adminService.listPartners(form.email)).find((u) => u.email === form.email.toLowerCase());
      if (created) await adminService.toggleUser(created.id);
      toast({ title: 'Partenaire créé en attente' });
      setCreateOpen(false); setForm({ email: '', password: '', first_name: '', company_name: '', billing_mode: 'per_click', default_cpc: '0.30', posting_price: '2.00' });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const pendingDetailFields = [
    { key: 'profile.company_name', label: 'Société' },
    { key: 'first_name', label: 'Prénom' }, { key: 'last_name', label: 'Nom' },
    { key: 'email', label: 'Email' }, { key: 'signup_source', label: 'Provenance' },
    { key: 'utm_campaign', label: 'Campagne UTM' }, { key: 'signup_referrer', label: 'Referrer' },
    { key: 'created_at', label: 'Demandé le' },
  ];

  return (
    <div data-testid="admin-pending-partners">
      <AdminListHeader
        count={list.length}
        label="partenaire à valider"
        onCreate={() => setCreateOpen(true)}
        createLabel="Nouveau partenaire en attente"
        createTestId="pending-create-btn"
      >
        <div className="flex gap-2">
          <Input placeholder="Société, nom, email..." value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load()} data-testid="pending-partners-search" className="w-64" />
          <Button variant="outline" size="sm" onClick={load} data-testid="pending-partners-search-btn"><Search className="h-4 w-4 mr-1" />Rechercher</Button>
        </div>
      </AdminListHeader>
      <Card className="rounded-2xl">
        <CardHeader>
          <CardTitle className="font-heading text-lg flex items-center gap-2">
            <Handshake className="h-5 w-5 text-brand" />Partenaires en attente de validation
            {list.length > 0 && <Badge className="bg-amber-100 text-amber-700 ml-1">{list.length}</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-2">
          <Table>
            <TableHeader><TableRow><TableHead>Société</TableHead><TableHead>Contact</TableHead><TableHead>Email</TableHead><TableHead>Provenance</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {list.length === 0 ? (
                <TableRow><TableCell colSpan={5} className="text-center text-slate-400 py-8">Aucun partenaire en attente</TableCell></TableRow>
              ) : list.map((p) => (
                <TableRow key={p.id} data-testid={`pending-partner-${p.id}`}>
                  <TableCell className="font-medium">
                    <DetailLinkCell onOpen={() => setDetailFor(p)} testId={`pending-detail-${p.id}`}>
                      {p.profile?.company_name || '—'}
                    </DetailLinkCell>
                  </TableCell>
                  <TableCell>{p.first_name} {p.last_name}</TableCell>
                  <TableCell className="text-slate-500">{p.email}</TableCell>
                  <TableCell>{p.signup_source ? <Badge className="bg-slate-100 text-slate-600">{p.signup_source}</Badge> : <span className="text-slate-300 text-xs">—</span>}</TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button variant="ghost" size="sm" onClick={() => setEditFor({ ...p })} title="Modifier" data-testid={`pending-edit-${p.id}`}><Pencil className="h-4 w-4 text-slate-600" /></Button>
                    <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white" disabled={validating === p.id} onClick={() => validate(p)} data-testid={`validate-partner-${p.id}`}>
                      <CheckCircle2 className="h-4 w-4 mr-1" />{validating === p.id ? '...' : 'Valider'}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <DetailDialog open={!!detailFor} onOpenChange={(o) => !o && setDetailFor(null)} title={`En attente — ${detailFor?.profile?.company_name || ''}`} record={detailFor} fields={pendingDetailFields} />

      {/* Edit */}
      <Dialog open={!!editFor} onOpenChange={(o) => !o && setEditFor(null)}>
        <DialogContent className="sm:max-w-md" data-testid="pending-edit-dialog">
          <DialogHeader><DialogTitle className="font-heading">Modifier le partenaire</DialogTitle></DialogHeader>
          {editFor && (
            <div className="space-y-3">
              <div><Label>Prénom / contact</Label><Input value={editFor.first_name || ''} onChange={(e) => setEditFor({ ...editFor, first_name: e.target.value })} /></div>
              <div><Label>Nom</Label><Input value={editFor.last_name || ''} onChange={(e) => setEditFor({ ...editFor, last_name: e.target.value })} /></div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditFor(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={saveEdit} data-testid="pending-edit-save">Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create pending partner */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-lg" data-testid="pending-create-dialog">
          <DialogHeader><DialogTitle className="font-heading">Nouveau partenaire en attente</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Contact</Label><Input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></div>
            <div><Label>Société</Label><Input value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} /></div>
            <div className="col-span-2"><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div className="col-span-2"><Label>Mot de passe</Label><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={createPending} data-testid="pending-create-save">Créer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

const CountriesTab = () => {
  const { toast } = useToast();
  const [list, setList] = useState([]);
  const [form, setForm] = useState({ code: '', label: '', url: '' });
  const [editing, setEditing] = useState(null); // {id, ...}
  const [detailFor, setDetailFor] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = () => adminService.listFooterCountries().then(setList).catch(() => {});
  useEffect(() => { load(); }, []);

  const add = async () => {
    if (!form.code.trim() || !form.label.trim()) { toast({ title: 'Code pays et libellé requis', variant: 'destructive' }); return; }
    try {
      await adminService.createFooterCountry({ code: form.code, label: form.label, url: form.url });
      setForm({ code: '', label: '', url: '' });
      setCreateOpen(false);
      toast({ title: 'Pays ajouté' });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const saveEdit = async () => {
    try {
      await adminService.updateFooterCountry(editing.id, {
        code: editing.code, label: editing.label, url: editing.url || '#', order: parseInt(editing.order),
      });
      setEditing(null);
      toast({ title: 'Pays mis à jour' });
      load();
    } catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const toggle = async (c) => {
    try { await adminService.updateFooterCountry(c.id, { is_active: !c.is_active }); load(); }
    catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const remove = async (c) => {
    if (!window.confirm(`Supprimer « ${c.label} » ?`)) return;
    try { await adminService.deleteFooterCountry(c.id); load(); toast({ title: 'Pays supprimé' }); }
    catch (e) { toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' }); }
  };

  const flag = (code) => `https://flagcdn.com/w40/${(code || '').toLowerCase()}.png`;

  const countryDetailFields = [
    { key: 'code', label: 'Code ISO', render: (v) => (v || '').toUpperCase() },
    { key: 'label', label: 'Libellé' },
    { key: 'url', label: 'URL' },
    { key: 'order', label: "Ordre d'affichage" },
    { key: 'is_active', label: 'Actif' },
  ];

  return (
    <div data-testid="admin-countries">
      <AdminListHeader
        count={list.length}
        label="alerte pays"
        onCreate={() => setCreateOpen(true)}
        createLabel="Nouvelle alerte pays"
        createTestId="country-create-btn"
      />

      <Card className="rounded-2xl">
        <CardContent className="pt-6">
          <Table>
            <TableHeader><TableRow><TableHead>Drapeau</TableHead><TableHead>Code</TableHead><TableHead>Libellé</TableHead><TableHead>Lien</TableHead><TableHead>Statut</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {list.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center text-slate-400 py-8">Aucun pays</TableCell></TableRow>
              ) : list.map((c) => (
                <TableRow key={c.id} data-testid={`country-row-${c.code}`}>
                  <TableCell><img src={flag(c.code)} alt={c.code} className="h-4 w-6 object-cover rounded-[2px] ring-1 ring-slate-200" onError={(e) => { e.currentTarget.style.display = 'none'; }} /></TableCell>
                  <TableCell className="uppercase font-medium">
                    <DetailLinkCell onOpen={() => setDetailFor(c)} testId={`country-detail-${c.code}`}>{c.code}</DetailLinkCell>
                  </TableCell>
                  <TableCell>{c.label}</TableCell>
                  <TableCell className="text-slate-500 text-sm truncate max-w-[220px]">
                    {c.url && c.url !== '#'
                      ? <a href={c.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline" data-testid={`country-link-${c.code}`}>{c.url}<ExternalLink className="h-3 w-3 shrink-0" /></a>
                      : <span className="text-slate-300">—</span>}
                  </TableCell>
                  <TableCell>{c.is_active ? <Badge className="bg-emerald-100 text-emerald-700">Actif</Badge> : <Badge className="bg-slate-200 text-slate-600">Masqué</Badge>}</TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <Button variant="ghost" size="sm" onClick={() => setEditing({ ...c })} title="Modifier" data-testid={`country-edit-${c.code}`}><Pencil className="h-4 w-4 text-slate-600" /></Button>
                    <Button variant="ghost" size="sm" onClick={() => toggle(c)} title={c.is_active ? 'Masquer' : 'Afficher'} data-testid={`country-toggle-${c.code}`}><Power className="h-4 w-4" /></Button>
                    <Button variant="ghost" size="sm" className="text-red-500" onClick={() => remove(c)} data-testid={`country-delete-${c.code}`}><Trash2 className="h-4 w-4" /></Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <DetailDialog open={!!detailFor} onOpenChange={(o) => !o && setDetailFor(null)} title={`Alerte pays — ${detailFor?.label || ''}`} record={detailFor} fields={countryDetailFields} />

      {/* Create country dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent data-testid="country-create-dialog">
          <DialogHeader><DialogTitle className="font-heading flex items-center gap-2"><Globe className="h-5 w-5 text-brand" />Nouvelle alerte pays</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Code pays (ISO 2 lettres)</Label>
              <div className="flex items-center gap-2">
                <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="es, de, gb…" data-testid="country-code-input" />
                {form.code.length === 2 && <img src={flag(form.code)} alt="" className="h-4 w-6 object-cover rounded-[2px] ring-1 ring-slate-200" onError={(e) => { e.currentTarget.style.display = 'none'; }} />}
              </div>
            </div>
            <div><Label>Libellé</Label><Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="Empleo en España" data-testid="country-label-input" /></div>
            <div><Label>Lien (URL)</Label><Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder={form.code.length === 2 ? `https://${form.code.toLowerCase()}.joboolo.com` : 'https://es.joboolo.com'} data-testid="country-url-input" /></div>
            <p className="text-xs text-slate-400">Laissez vide pour générer automatiquement le sous-domaine <code>https://[code].joboolo.com</code>.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={add} data-testid="country-add-btn"><Plus className="h-4 w-4 mr-1" />Ajouter</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!editing} onOpenChange={(o) => { if (!o) setEditing(null); }}>
        <DialogContent data-testid="country-edit-dialog">
          <DialogHeader><DialogTitle className="font-heading">Modifier le pays</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-3">
              <div><Label>Code pays (ISO 2 lettres)</Label><Input value={editing.code} onChange={(e) => setEditing({ ...editing, code: e.target.value })} data-testid="country-edit-code" /></div>
              <div><Label>Libellé</Label><Input value={editing.label} onChange={(e) => setEditing({ ...editing, label: e.target.value })} data-testid="country-edit-label" /></div>
              <div><Label>Lien (URL)</Label><Input value={editing.url} onChange={(e) => setEditing({ ...editing, url: e.target.value })} data-testid="country-edit-url" /></div>
              <div><Label>Ordre d'affichage</Label><Input type="number" value={editing.order} onChange={(e) => setEditing({ ...editing, order: e.target.value })} data-testid="country-edit-order" /></div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Annuler</Button>
            <Button className="bg-brand hover:bg-brand-hover" onClick={saveEdit} data-testid="country-edit-save">Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

// ---------- Main ----------
const AdminDashboard = () => {
  const { isAuthenticated, user, logout } = useAuth();
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (isAuthenticated && user?.user_type === 'admin') {
      adminService.stats().then(setStats).catch(() => {});
    }
  }, [isAuthenticated, user]);

  if (!isAuthenticated || user?.user_type !== 'admin') {
    return <AdminLogin />;
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-slate-900 text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <span className="font-heading text-xl font-extrabold">Admin <span className="text-brand">Joboolo</span></span>
          <Button variant="ghost" className="text-slate-200 hover:text-white hover:bg-slate-800" onClick={logout} data-testid="admin-logout"><LogOut className="h-4 w-4 mr-2" />Déconnexion</Button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="admin-dashboard">
        <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900 mb-6">Tableau de bord</h1>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard icon={Users} label="Candidats" value={stats?.candidates} />
          <StatCard icon={Building2} label="Employeurs" value={stats?.employers} />
          <StatCard icon={Handshake} label="Partenaires" value={stats?.partners} />
          <StatCard icon={Briefcase} label="Offres actives" value={stats?.active_jobs} />
        </div>

        <Tabs defaultValue="candidates">
          <TabsList className="mb-6">
            <TabsTrigger value="candidates" data-testid="tab-candidates">Candidats</TabsTrigger>
            <TabsTrigger value="employers" data-testid="tab-employers">Employeurs</TabsTrigger>
            <TabsTrigger value="partners" data-testid="tab-partners">Partenaires</TabsTrigger>
            <TabsTrigger value="pending" data-testid="tab-pending">En attente</TabsTrigger>
            <TabsTrigger value="jobs" data-testid="tab-jobs">Offres</TabsTrigger>
            <TabsTrigger value="feeds" data-testid="tab-feeds">Flux XML</TabsTrigger>
            <TabsTrigger value="alerts" data-testid="tab-alerts">Alertes</TabsTrigger>
            <TabsTrigger value="countries" data-testid="tab-countries">Pays</TabsTrigger>
            <TabsTrigger value="settings" data-testid="tab-settings">Paramètres</TabsTrigger>
          </TabsList>
          <TabsContent value="candidates"><UsersTab userType="candidate" testid="admin-candidates" /></TabsContent>
          <TabsContent value="employers"><UsersTab userType="employer" testid="admin-employers" /></TabsContent>
          <TabsContent value="partners"><PartnersTab /></TabsContent>
          <TabsContent value="pending"><PendingPartnersTab /></TabsContent>
          <TabsContent value="jobs"><JobsTab /></TabsContent>
          <TabsContent value="feeds"><FeedsTab /></TabsContent>
          <TabsContent value="alerts"><AlertsTab /></TabsContent>
          <TabsContent value="countries"><CountriesTab /></TabsContent>
          <TabsContent value="settings"><SettingsTab /></TabsContent>
        </Tabs>
      </div>
    </div>
  );
};

export default AdminDashboard;
