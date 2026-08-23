import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Header from '../components/Header';
import Footer from '../components/Footer';
import AuthModal from '../components/AuthModal';
import RecruiterCheckoutDialog from '../components/RecruiterCheckoutDialog';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '../components/ui/accordion';
import { useAuth } from '../contexts/AuthContext';
import { recruiterService } from '../services/recruiterService';
import { useToast } from '../hooks/use-toast';
import {
  Sparkles, ArrowRight, Check, CheckCircle2, Target, MousePointerClick, UserCheck,
  Search, Users, Zap, ShieldCheck, Clock, Quote, FileCode2, RefreshCw, Globe, Link2,
} from 'lucide-react';

const HERO_IMG = 'https://images.unsplash.com/photo-1758518731706-be5d5230e5a5?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200';
const FEATURE_IMG = 'https://images.pexels.com/photos/36733331/pexels-photo-36733331.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=750&w=1000';

const STATS = [
  { number: '150 000+', label: 'Candidats qualifiés actifs' },
  { number: '48h', label: 'Délai moyen du 1er entretien' },
  { number: '95%', label: 'Taux de satisfaction employeur' },
];

const STEPS = [
  { icon: Zap, title: '1. Choisissez votre formule', desc: 'Publiez instantanément votre offre Premium ou confiez-nous une mission de sourcing sur-mesure.' },
  { icon: Target, title: '2. Ciblez avec précision', desc: 'Votre annonce est diffusée auprès des profils les plus pertinents de notre réseau qualifié.' },
  { icon: UserCheck, title: '3. Rencontrez vos talents', desc: 'Recevez des candidatures ciblées et engagez la conversation sans perdre de temps.' },
];

const TESTIMONIALS = [
  { quote: "Grâce à l'offre Premium, nous avons recruté notre Lead Dev en moins d'une semaine. La qualité des profils est incomparable.", author: 'Marie L.', role: 'DRH, TechStart' },
  { quote: "Le service de candidats sur-mesure nous a fait gagner des dizaines d'heures. L'équipe a parfaitement compris notre culture d'entreprise.", author: 'Thomas V.', role: 'CEO, InnovAgency' },
];

const FAQ = [
  { q: "Puis-je payer mon annonce Premium directement en ligne ?", a: "Oui, le paiement est 100% sécurisé via Stripe. Vos crédits d'offres Premium sont ajoutés instantanément à votre compte après validation." },
  { q: "Comment fonctionne le modèle Au clic (CPC) ?", a: "Vous définissez un budget maximum et ne payez que lorsqu'un candidat clique réellement sur votre offre. C'est le format idéal pour maîtriser vos coûts au plus près." },
  { q: "Qu'inclut le service Candidats ciblés sur-mesure ?", a: "Un expert dédié prend en charge le sourcing, la qualification téléphonique et vous présente uniquement une short-list de candidats parfaitement ciblés et pré-sélectionnés." },
  { q: "Sous quel délai suis-je recontacté après une demande de devis ?", a: "Un de nos experts vous recontacte sous 24h ouvrées avec une proposition adaptée à vos enjeux de recrutement." },
];

const RecruiterLanding = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { isAuthenticated, isEmployer } = useAuth();
  const [authOpen, setAuthOpen] = useState(false);
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [quoteNeed, setQuoteNeed] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [unitPrice, setUnitPrice] = useState(null);
  const [form, setForm] = useState({ first_name: '', last_name: '', company: '', email: '', phone: '', message: '' });
  const quoteRef = useRef(null);

  useEffect(() => {
    recruiterService.getPacks().then((d) => setUnitPrice(d.unit_price)).catch(() => {});
  }, []);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const handlePublish = () => {
    if (isAuthenticated && isEmployer) setCheckoutOpen(true);
    else setAuthOpen(true);
  };

  const scrollToQuote = (need = null) => {
    setQuoteNeed(need);
    quoteRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const submitQuote = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await recruiterService.requestQuote({ ...form, need: quoteNeed || null });
      toast({ title: 'Demande envoyée', description: res.message });
      setForm({ first_name: '', last_name: '', company: '', email: '', phone: '', message: '' });
    } catch (err) {
      toast({ title: 'Erreur', description: err.response?.data?.detail || err.message, variant: 'destructive' });
    } finally {
      setSubmitting(false);
    }
  };

  const tiers = [
    {
      id: 'cpc', name: 'Au clic (CPC)', target: 'Budget flexible', price: 'Sur mesure', period: '',
      features: ['Paiement uniquement au clic qualifié', 'Maîtrise totale du budget', 'Diffusion ciblée', 'Statistiques en temps réel'],
      cta: 'Créer une campagne', style: 'outline', onClick: () => scrollToQuote('cpc'), featured: false,
    },
    {
      id: 'premium', name: 'Offre Premium', target: 'Idéal pour un besoin urgent',
      price: unitPrice != null ? `${Math.round(unitPrice)}€` : '—', period: '/ offre', fromPrefix: true,
      badge: 'Le plus populaire',
      features: ['Publication pendant 30 jours', 'Mise en avant en tête de liste', 'Alerte email ciblée aux candidats', 'Paiement sécurisé via Stripe'],
      cta: 'Publier maintenant', style: 'primary', onClick: handlePublish, featured: true,
    },
  ];

  return (
    <div className="min-h-screen bg-white" data-testid="recruiter-landing-page">
      <Header />

      {/* HERO */}
      <section className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 lg:py-24">
          <div className="grid lg:grid-cols-12 gap-12 items-center">
            <div className="lg:col-span-7 animate-fade-up">
              <Badge className="bg-brand-50 text-brand hover:bg-brand-50 border-0 rounded-full px-3 py-1 mb-6" data-testid="hero-badge">
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />Solution Recruteurs Premium
              </Badge>
              <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tighter text-slate-900 leading-[1.05]">
                Recrutez les meilleurs talents.<br />
                <span className="text-brand">Plus vite. Plus loin.</span>
              </h1>
              <p className="mt-6 text-base md:text-lg text-slate-500 max-w-xl leading-relaxed">
                Accédez à une audience premium de candidats qualifiés sur Joboolo. Publiez à l'unité, au clic,
                ou laissez nos experts sourcer vos futurs collaborateurs sur-mesure.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row gap-3">
                <Button
                  onClick={handlePublish}
                  className="rounded-full bg-brand hover:bg-brand-hover text-white px-7 h-12 text-base transition-transform active:scale-95"
                  data-testid="hero-cta-publish"
                >
                  Publier une offre<ArrowRight className="h-4 w-4 ml-2" />
                </Button>
                <Button
                  variant="outline"
                  onClick={() => scrollToQuote(null)}
                  className="rounded-full px-7 h-12 text-base border-slate-300 hover:border-brand hover:text-brand"
                  data-testid="hero-cta-quote"
                >
                  Demander un devis
                </Button>
              </div>
              <div className="mt-8 flex items-center gap-6 text-sm text-slate-500">
                <span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-brand" />Paiement sécurisé Stripe</span>
                <span className="flex items-center gap-2"><Clock className="h-4 w-4 text-brand" />Mise en ligne immédiate</span>
              </div>
            </div>

            <div className="lg:col-span-5 animate-fade-up" style={{ animationDelay: '120ms' }}>
              <div className="relative">
                <div className="absolute -top-6 -right-6 h-40 w-40 rounded-3xl bg-brand-100 -z-10" />
                <div className="absolute -bottom-6 -left-6 h-28 w-28 rounded-2xl bg-brand/10 -z-10" />
                <img
                  src={HERO_IMG}
                  alt="Équipe de professionnels en réunion dans un bureau moderne"
                  className="rounded-2xl shadow-2xl w-full object-cover aspect-[4/3]"
                  data-testid="hero-image"
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* STATS */}
      <section className="bg-slate-50/70 border-y border-slate-100">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-slate-200">
            {STATS.map((s, i) => (
              <div key={i} className="text-center py-6 md:py-2" data-testid={`stat-${i}`}>
                <div className="font-heading text-4xl lg:text-5xl font-extrabold tracking-tight text-slate-900">{s.number}</div>
                <div className="text-sm text-slate-500 mt-2">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="py-20 lg:py-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-slate-900">Un processus de recrutement simplifié</h2>
            <p className="text-slate-500 mt-3">De la publication à la rencontre de vos talents, en trois étapes.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {STEPS.map((s, i) => (
              <div key={i} className="rounded-2xl border border-slate-100 p-8 text-center bg-white hover:-translate-y-1 hover:shadow-xl transition-all duration-300" data-testid={`step-${i}`}>
                <div className="h-14 w-14 rounded-2xl bg-brand-50 text-brand flex items-center justify-center mx-auto mb-5">
                  <s.icon className="h-7 w-7" />
                </div>
                <h3 className="font-heading text-lg font-semibold text-slate-900 mb-2">{s.title}</h3>
                <p className="text-slate-500 text-sm leading-relaxed">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* IMPORT AUTOMATIQUE DES OFFRES */}
      <section id="import" className="py-20 lg:py-24 bg-[#0A0A0A]">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-14 items-center">
            <div>
              <Badge className="bg-brand/15 text-brand hover:bg-brand/15 border-0 rounded-full px-3 py-1 mb-5">
                <RefreshCw className="h-3.5 w-3.5 mr-1.5" />Import automatique
              </Badge>
              <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-white leading-tight">
                Importez toutes vos offres automatiquement
              </h2>
              <p className="text-slate-400 mt-4 text-base leading-relaxed">
                Ne ressaisissez plus jamais une annonce à la main. Connectez votre flux XML ou n'importe quelle source
                en ligne (ATS, site carrière, multiposting) et vos offres se publient et se mettent à jour toutes seules
                sur Joboolo.
              </p>
              <ul className="mt-8 space-y-4">
                {[
                  { icon: FileCode2, title: 'Fichier XML', text: 'Fournissez l\'URL de votre flux : import et synchronisation automatiques.' },
                  { icon: Globe, title: 'Autre source en ligne', text: 'ATS, site carrière, agrégateur ou API — nous nous adaptons à votre système.' },
                  { icon: RefreshCw, title: 'Mise à jour continue', text: 'Vos annonces restent à jour sans la moindre intervention de votre part.' },
                ].map((b, i) => (
                  <li key={i} className="flex items-start gap-3" data-testid={`import-bullet-${i}`}>
                    <span className="h-10 w-10 rounded-xl bg-brand/15 text-brand flex items-center justify-center shrink-0">
                      <b.icon className="h-5 w-5" />
                    </span>
                    <div>
                      <div className="text-white font-semibold text-sm">{b.title}</div>
                      <div className="text-slate-400 text-sm">{b.text}</div>
                    </div>
                  </li>
                ))}
              </ul>
              <Button onClick={() => scrollToQuote('import')} className="mt-8 rounded-full bg-brand hover:bg-brand-hover text-white px-7 h-12" data-testid="import-cta">
                Importer mes offres<ArrowRight className="h-4 w-4 ml-2" />
              </Button>
            </div>

            <div className="relative">
              <div className="rounded-2xl bg-white/5 border border-white/10 p-6 backdrop-blur-sm">
                <div className="flex items-center gap-2 mb-5">
                  <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-yellow-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-green-400" />
                  <span className="ml-2 text-xs text-slate-400 font-mono">feed-import.xml</span>
                </div>
                <div className="space-y-3">
                  {[
                    { icon: FileCode2, label: 'flux-entreprise.xml', status: 'Synchronisé', ok: true },
                    { icon: Link2, label: 'api.mon-ats.com/jobs', status: 'Connecté', ok: true },
                    { icon: Globe, label: 'carriere.masociete.fr', status: 'Import en cours', ok: false },
                  ].map((r, i) => (
                    <div key={i} className="flex items-center justify-between rounded-xl bg-white/5 border border-white/10 px-4 py-3">
                      <span className="flex items-center gap-3 text-slate-200 text-sm">
                        <r.icon className="h-4.5 w-4.5 text-brand" />{r.label}
                      </span>
                      <span className={`text-xs px-2.5 py-1 rounded-full ${r.ok ? 'bg-green-400/15 text-green-300' : 'bg-brand/15 text-brand'}`}>
                        {r.ok ? <CheckCircle2 className="h-3 w-3 inline mr-1" /> : <RefreshCw className="h-3 w-3 inline mr-1 animate-spin" />}{r.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section id="tarifs" className="py-20 lg:py-24 bg-slate-50/70 border-y border-slate-100">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-slate-900">Des solutions adaptées à vos enjeux</h2>
            <p className="text-slate-500 mt-3">Choisissez la formule qui correspond à votre besoin de recrutement.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch max-w-3xl mx-auto">
            {tiers.map((t) => (
              <div
                key={t.id}
                className={`relative rounded-2xl bg-white p-8 flex flex-col transition-all duration-300 hover:-translate-y-1 hover:shadow-xl ${t.featured ? 'border-2 border-brand shadow-lg md:scale-105 z-10' : 'border border-slate-200'}`}
                data-testid={`tier-${t.id}`}
              >
                {t.badge && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-brand text-white text-xs font-semibold px-3 py-1 rounded-full">
                    {t.badge}
                  </span>
                )}
                <div className="mb-5">
                  <h3 className="font-heading text-xl font-bold text-slate-900">{t.name}</h3>
                  <p className="text-sm text-slate-500 mt-1">{t.target}</p>
                </div>
                <div className="mb-6">
                  {t.fromPrefix && <div className="text-xs font-medium text-slate-400 mb-0.5">À partir de</div>}
                  <div className="flex items-end gap-1">
                    <span className="font-heading text-4xl font-extrabold tracking-tight text-slate-900">{t.price}</span>
                    {t.period && <span className="text-slate-400 text-sm mb-1.5">{t.period}</span>}
                  </div>
                </div>
                <ul className="space-y-3 mb-8 flex-1">
                  {t.features.map((f, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-sm text-slate-600">
                      <Check className="h-4.5 w-4.5 text-brand shrink-0 mt-0.5" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <Button
                  onClick={t.onClick}
                  className={t.style === 'primary'
                    ? 'w-full rounded-full bg-brand hover:bg-brand-hover text-white h-11'
                    : 'w-full rounded-full h-11'}
                  variant={t.style === 'primary' ? 'default' : 'outline'}
                  data-testid={`tier-cta-${t.id}`}
                >
                  {t.cta}
                </Button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FEATURE : Candidats ciblés */}
      <section id="candidats" className="py-20 lg:py-28">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-14 items-center">
            <div className="relative order-2 lg:order-1">
              <div className="absolute -bottom-6 -right-6 h-36 w-36 rounded-3xl bg-brand-100 -z-10" />
              <img
                src={FEATURE_IMG}
                alt="Deux professionnels échangeant dans un bureau lumineux"
                className="rounded-2xl shadow-xl w-full object-cover aspect-[4/3]"
                data-testid="feature-image"
              />
            </div>
            <div className="order-1 lg:order-2">
              <Badge className="bg-brand-50 text-brand hover:bg-brand-50 border-0 rounded-full px-3 py-1 mb-5">
                <Target className="h-3.5 w-3.5 mr-1.5" />Candidats parfaitement ciblés
              </Badge>
              <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-slate-900 leading-tight">
                Ne perdez plus de temps avec les CV non pertinents
              </h2>
              <p className="text-slate-500 mt-4 text-base leading-relaxed">
                Notre promesse : des candidats sélectionnés et parfaitement ciblés pour votre entreprise. La qualité
                avant la quantité, à chaque recrutement.
              </p>
              <ul className="mt-8 space-y-4">
                {[
                  { icon: Search, text: 'Matching intelligent basé sur les compétences réelles.' },
                  { icon: Clock, text: 'Gain de temps massif sur votre présélection.' },
                ].map((b, i) => (
                  <li key={i} className="flex items-start gap-3" data-testid={`feature-bullet-${i}`}>
                    <span className="h-9 w-9 rounded-xl bg-brand-50 text-brand flex items-center justify-center shrink-0">
                      <b.icon className="h-4.5 w-4.5" />
                    </span>
                    <span className="text-slate-700 text-sm pt-1.5">{b.text}</span>
                  </li>
                ))}
              </ul>
              <Button onClick={() => scrollToQuote('targeted')} className="mt-8 rounded-full bg-brand hover:bg-brand-hover text-white px-7 h-12" data-testid="feature-cta">
                Recevoir des candidats ciblés<ArrowRight className="h-4 w-4 ml-2" />
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* TESTIMONIALS */}
      <section className="py-20 bg-slate-50/70 border-y border-slate-100">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-slate-900">Ce que pensent nos recruteurs</h2>
          </div>
          <div className="grid md:grid-cols-2 gap-6">
            {TESTIMONIALS.map((t, i) => (
              <div key={i} className="rounded-2xl bg-white border border-slate-200 p-8" data-testid={`testimonial-${i}`}>
                <Quote className="h-8 w-8 text-brand/30 mb-4" />
                <p className="text-slate-700 leading-relaxed">« {t.quote} »</p>
                <div className="mt-6 flex items-center gap-3">
                  <span className="h-11 w-11 rounded-full bg-brand text-white flex items-center justify-center font-heading font-bold">
                    {t.author.charAt(0)}
                  </span>
                  <div>
                    <div className="font-semibold text-slate-900 text-sm">{t.author}</div>
                    <div className="text-xs text-slate-500">{t.role}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-20 lg:py-24">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-slate-900">Questions fréquentes</h2>
          </div>
          <Accordion type="single" collapsible className="w-full" data-testid="faq-accordion">
            {FAQ.map((f, i) => (
              <AccordionItem key={i} value={`item-${i}`} data-testid={`faq-item-${i}`}>
                <AccordionTrigger className="text-left font-medium text-slate-900">{f.q}</AccordionTrigger>
                <AccordionContent className="text-slate-500 leading-relaxed">{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </section>

      {/* QUOTE FORM */}
      <section ref={quoteRef} id="devis" className="py-20 lg:py-24 bg-slate-50/70 border-y border-slate-100 scroll-mt-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 items-start">
            <div>
              <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-slate-900">Parlons de vos besoins de recrutement</h2>
              <p className="text-slate-500 mt-4 text-base leading-relaxed">
                Remplissez ce formulaire et un de nos experts vous recontactera sous 24h ouvrées avec une proposition
                sur-mesure.
              </p>
              <ul className="mt-8 space-y-3">
                {['Réponse sous 24h ouvrées', 'Stratégie de sourcing personnalisée', 'Sans engagement'].map((b, i) => (
                  <li key={i} className="flex items-center gap-3 text-slate-700 text-sm">
                    <CheckCircle2 className="h-5 w-5 text-brand" />{b}
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-2xl bg-white border border-slate-200 p-6 sm:p-8 shadow-sm">
              <form onSubmit={submitQuote} className="space-y-4" data-testid="quote-form">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="q-first">Prénom</Label>
                    <Input id="q-first" required value={form.first_name} onChange={(e) => set('first_name', e.target.value)} placeholder="Marie" data-testid="quote-firstname" />
                  </div>
                  <div>
                    <Label htmlFor="q-last">Nom</Label>
                    <Input id="q-last" required value={form.last_name} onChange={(e) => set('last_name', e.target.value)} placeholder="Dupont" data-testid="quote-lastname" />
                  </div>
                </div>
                <div>
                  <Label htmlFor="q-company">Entreprise</Label>
                  <Input id="q-company" required value={form.company} onChange={(e) => set('company', e.target.value)} placeholder="Votre société" data-testid="quote-company" />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="q-email">Email professionnel</Label>
                    <Input id="q-email" type="email" required value={form.email} onChange={(e) => set('email', e.target.value)} placeholder="marie@societe.fr" data-testid="quote-email" />
                  </div>
                  <div>
                    <Label htmlFor="q-phone">Téléphone</Label>
                    <Input id="q-phone" value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="06 12 34 56 78" data-testid="quote-phone" />
                  </div>
                </div>
                <div>
                  <Label htmlFor="q-message">Décrivez votre besoin (optionnel)</Label>
                  <Textarea id="q-message" rows={4} value={form.message} onChange={(e) => set('message', e.target.value)} placeholder="Postes à pourvoir, secteur, délais..." data-testid="quote-message" />
                </div>
                <Button type="submit" disabled={submitting} className="w-full rounded-full bg-brand hover:bg-brand-hover text-white h-12" data-testid="quote-submit">
                  {submitting ? 'Envoi...' : 'Demander un devis'}
                </Button>
              </form>
            </div>
          </div>
        </div>
      </section>

      {/* FINAL CTA BAND */}
      <section className="bg-[#0A0A0A] py-20 lg:py-24">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <Users className="h-10 w-10 text-brand mx-auto mb-6" />
          <h2 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-white">Prêt à trouver votre perle rare ?</h2>
          <p className="text-slate-400 mt-4 max-w-xl mx-auto">
            Rejoignez les milliers d'entreprises qui recrutent efficacement avec Joboolo.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row gap-3 justify-center">
            <Button onClick={() => setAuthOpen(true)} className="rounded-full bg-brand hover:bg-brand-hover text-white px-8 h-12 text-base" data-testid="final-cta-signup">
              Créer mon compte recruteur<ArrowRight className="h-4 w-4 ml-2" />
            </Button>
            <Button onClick={handlePublish} variant="outline" className="rounded-full px-8 h-12 text-base border-white/20 text-white bg-transparent hover:bg-white/10 hover:text-white" data-testid="final-cta-publish">
              <MousePointerClick className="h-4 w-4 mr-2" />Publier une offre Premium
            </Button>
          </div>
        </div>
      </section>

      <Footer />

      <AuthModal isOpen={authOpen} onClose={() => setAuthOpen(false)} />
      <RecruiterCheckoutDialog open={checkoutOpen} onOpenChange={setCheckoutOpen} />
    </div>
  );
};

export default RecruiterLanding;
