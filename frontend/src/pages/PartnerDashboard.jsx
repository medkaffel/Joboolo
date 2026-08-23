import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { paymentService } from '../services/paymentService';
import { useToast } from '../hooks/use-toast';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { RechargeDialog } from '../components/RechargeDialog';
import PartnerCampaigns from '../components/PartnerCampaigns';
import PartnerPerformance from '../components/PartnerPerformance';
import { Wallet, MousePointerClick, TrendingUp, Briefcase, LogOut, CreditCard, Handshake, ImagePlus } from 'lucide-react';

const StatCard = ({ icon: Icon, label, value, accent }) => (
  <Card className="rounded-2xl">
    <CardContent className="p-5 flex items-center gap-4">
      <div className={`h-11 w-11 rounded-xl flex items-center justify-center ${accent || 'bg-brand/10 text-brand'}`}><Icon className="h-5 w-5" /></div>
      <div>
        <div className="font-heading text-2xl font-bold text-slate-900">{value ?? '—'}</div>
        <div className="text-sm text-slate-500">{label}</div>
      </div>
    </CardContent>
  </Card>
);

const PartnerLogin = () => {
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
  };

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <Card className="w-full max-w-md rounded-2xl">
        <CardHeader>
          <CardTitle className="font-heading text-2xl text-center flex items-center justify-center gap-2">
            <Handshake className="h-6 w-6 text-brand" /> Espace <span className="text-brand">Partenaire</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <Label htmlFor="p-email">Email</Label>
              <Input id="p-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required data-testid="partner-login-email" />
            </div>
            <div>
              <Label htmlFor="p-password">Mot de passe</Label>
              <Input id="p-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required data-testid="partner-login-password" />
            </div>
            <Button type="submit" disabled={loading} className="w-full bg-brand hover:bg-brand-hover" data-testid="partner-login-btn">
              {loading ? 'Connexion...' : 'Se connecter'}
            </Button>
          </form>
          <p className="text-xs text-slate-400 text-center mt-4">Vos identifiants partenaire sont fournis par l'équipe Joboolo.</p>
        </CardContent>
      </Card>
    </div>
  );
};

const PartnerDashboard = () => {
  const { isAuthenticated, user, logout } = useAuth();
  const [profile, setProfile] = useState(null);
  const [txns, setTxns] = useState([]);
  const [showRecharge, setShowRecharge] = useState(false);
  const [logoUploading, setLogoUploading] = useState(false);

  const isPartner = isAuthenticated && user?.user_type === 'partner';

  const load = () => {
    paymentService.partnerMe().then(setProfile).catch(() => {});
    paymentService.partnerTransactions().then(setTxns).catch(() => {});
  };

  const uploadLogo = async (file) => {
    if (!file) return;
    setLogoUploading(true);
    try {
      await paymentService.uploadPartnerLogo(file);
      load();
    } catch (e) {
      // silent
    } finally { setLogoUploading(false); }
  };

  useEffect(() => {
    if (isPartner) load();
    // eslint-disable-next-line
  }, [isPartner]);

  if (!isPartner) return <PartnerLogin />;

  const isPerClick = profile?.billing_mode === 'per_click';

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-slate-900 text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <span className="font-heading text-xl font-extrabold flex items-center gap-2"><Handshake className="h-5 w-5 text-brand" />Espace <span className="text-brand">Partenaire</span></span>
          <Button variant="ghost" className="text-slate-200 hover:text-white hover:bg-slate-800" onClick={logout} data-testid="partner-logout"><LogOut className="h-4 w-4 mr-2" />Déconnexion</Button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="partner-dashboard">
        <div className="flex items-center justify-between flex-wrap gap-4 mb-6">
          <div className="flex items-center gap-4">
            <div className="flex flex-col items-center gap-1">
              <div className="h-16 w-16 rounded-xl border border-slate-200 bg-white flex items-center justify-center overflow-hidden">
                {profile?.logo_url ? (
                  <img src={`${process.env.REACT_APP_BACKEND_URL}${profile.logo_url}`} alt="logo" className="h-full w-full object-contain" data-testid="partner-logo-img" />
                ) : (
                  <Handshake className="h-7 w-7 text-slate-300" />
                )}
              </div>
              <label className="inline-flex items-center gap-1 text-xs text-brand cursor-pointer">
                <ImagePlus className="h-3.5 w-3.5" />
                <input type="file" accept="image/*" className="hidden" onChange={(e) => uploadLogo(e.target.files?.[0])} disabled={logoUploading} data-testid="partner-logo-input" />
                {logoUploading ? '...' : 'Logo'}
              </label>
            </div>
            <div>
              <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900">{profile?.company_name || 'Tableau de bord'}</h1>
              <div className="text-slate-500 text-sm mt-1">
                Facturation : <Badge className="bg-brand/10 text-brand ml-1">{isPerClick ? 'Au clic (CPC)' : "À l'annonce"}</Badge>
              </div>
            </div>
          </div>
          <Button className="bg-brand hover:bg-brand-hover" onClick={() => setShowRecharge(true)} data-testid="partner-recharge-btn">
            <CreditCard className="h-4 w-4 mr-2" />{isPerClick ? 'Recharger mon solde' : 'Acheter des annonces'}
          </Button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard icon={Wallet} label="Solde disponible" value={`${(profile?.balance ?? 0).toFixed(2)} €`} accent="bg-emerald-100 text-emerald-700" />
          <StatCard icon={MousePointerClick} label="Clics reçus" value={profile?.total_clicks} />
          <StatCard icon={TrendingUp} label="Total dépensé" value={`${(profile?.total_spent ?? 0).toFixed(2)} €`} accent="bg-amber-100 text-amber-700" />
          <StatCard icon={Briefcase} label="Offres actives" value={profile?.active_jobs} />
        </div>

        {isPerClick && (
          <p className="text-sm text-slate-500 mb-6">CPC par défaut : <strong className="text-slate-800">{(profile?.default_cpc ?? 0).toFixed(2)} €/clic</strong>. Chaque clic sur vos offres déduit le CPC de votre solde.</p>
        )}
        {!isPerClick && (
          <p className="text-sm text-slate-500 mb-6">Annonces restantes : <strong className="text-slate-800">{profile?.postings_remaining}</strong>.</p>
        )}

        <PartnerPerformance />

        <PartnerCampaigns />

        <h2 className="font-heading text-xl font-semibold text-slate-900 mb-3">Historique des recharges</h2>
        <Card className="rounded-2xl">
          <Table>
            <TableHeader>
              <TableRow><TableHead>Date</TableHead><TableHead>Montant</TableHead><TableHead>Statut</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {txns.length === 0 ? (
                <TableRow><TableCell colSpan={3} className="text-center text-slate-400 py-8">Aucune recharge pour le moment</TableCell></TableRow>
              ) : txns.map((t, i) => (
                <TableRow key={i} data-testid={`partner-txn-${i}`}>
                  <TableCell className="text-slate-500">{t.created_at ? new Date(t.created_at).toLocaleString('fr-FR') : '—'}</TableCell>
                  <TableCell className="font-medium">{(t.amount ?? 0).toFixed(2)} €</TableCell>
                  <TableCell>
                    {t.payment_status === 'paid'
                      ? <Badge className="bg-emerald-100 text-emerald-700">Payée</Badge>
                      : t.payment_status === 'pending'
                        ? <Badge className="bg-slate-200 text-slate-600">En attente</Badge>
                        : <Badge className="bg-rose-100 text-rose-700">{t.payment_status}</Badge>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>

      <RechargeDialog open={showRecharge} onOpenChange={setShowRecharge} companyName={profile?.company_name} billingMode={profile?.billing_mode} postingPrice={profile?.posting_price} />
    </div>
  );
};

export default PartnerDashboard;
