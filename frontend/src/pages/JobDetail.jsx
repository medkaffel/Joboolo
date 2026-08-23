import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  MapPin, Building, Clock, Euro, Heart, Share2, Link as LinkIcon,
  Linkedin, Twitter, Mail, ChevronRight, CheckCircle2, Gift, ArrowLeft, Sparkles
} from 'lucide-react';
import { jobService } from '../services/jobService';
import { applicationService } from '../services/applicationService';
import { savedJobService } from '../services/savedJobService';
import { aiService } from '../services/aiService';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../hooks/use-toast';
import AuthModal from '../components/AuthModal';
import ApplyModal from '../components/ApplyModal';
import MatchDialog from '../components/MatchDialog';

const EMPLOYMENT_TYPE = {
  CDI: 'FULL_TIME', CDD: 'TEMPORARY', Stage: 'INTERN',
  Freelance: 'CONTRACTOR', 'Intérim': 'TEMPORARY', Titulaire: 'FULL_TIME',
};

const upsertMeta = (attr, key, content) => {
  let el = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
};

const useJobSeo = (job) => {
  useEffect(() => {
    if (!job) return;
    const prevTitle = document.title;
    const url = window.location.href;
    const company = job.company?.name || 'Entreprise';
    const title = `${job.title} - ${company} (${job.location}) | Joboolo`;
    const desc = (job.description || '')
      .replace(/\s+/g, ' ')
      .slice(0, 155)
      .trim() + '…';

    document.title = title;
    upsertMeta('name', 'description', desc);
    upsertMeta('property', 'og:title', title);
    upsertMeta('property', 'og:description', desc);
    upsertMeta('property', 'og:type', 'website');
    upsertMeta('property', 'og:url', url);
    upsertMeta('property', 'og:site_name', 'Joboolo');
    upsertMeta('name', 'twitter:card', 'summary_large_image');
    upsertMeta('name', 'twitter:title', title);
    upsertMeta('name', 'twitter:description', desc);

    // canonical
    let canonical = document.head.querySelector('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.setAttribute('rel', 'canonical');
      document.head.appendChild(canonical);
    }
    canonical.setAttribute('href', url);

    // JSON-LD JobPosting (Google for Jobs)
    const ld = {
      '@context': 'https://schema.org/',
      '@type': 'JobPosting',
      title: job.title,
      description: job.description,
      datePosted: job.created_at,
      employmentType: EMPLOYMENT_TYPE[job.job_type] || 'FULL_TIME',
      hiringOrganization: {
        '@type': 'Organization',
        name: company,
      },
      jobLocation: {
        '@type': 'Place',
        address: {
          '@type': 'PostalAddress',
          addressLocality: job.location,
          addressCountry: 'FR',
        },
      },
    };
    if (job.salary_min || job.salary_max) {
      ld.baseSalary = {
        '@type': 'MonetaryAmount',
        currency: job.salary_currency || 'EUR',
        value: {
          '@type': 'QuantitativeValue',
          minValue: job.salary_min || undefined,
          maxValue: job.salary_max || undefined,
          unitText: 'YEAR',
        },
      };
    }
    let script = document.getElementById('jobposting-ld');
    if (!script) {
      script = document.createElement('script');
      script.id = 'jobposting-ld';
      script.type = 'application/ld+json';
      document.head.appendChild(script);
    }
    script.textContent = JSON.stringify(ld);

    return () => {
      document.title = prevTitle;
      const s = document.getElementById('jobposting-ld');
      if (s) s.remove();
    };
  }, [job]);
};

const JobDetail = () => {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const { isAuthenticated, isCandidate } = useAuth();
  const { toast } = useToast();

  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [applying, setApplying] = useState(false);
  const [isSaved, setIsSaved] = useState(false);
  const [savingJob, setSavingJob] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [showApplyModal, setShowApplyModal] = useState(false);
  const [matchOpen, setMatchOpen] = useState(false);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchResult, setMatchResult] = useState(null);

  const handleAnalyze = async () => {
    if (!isAuthenticated) { setShowAuthModal(true); return; }
    if (!isCandidate) {
      toast({ title: 'Réservé aux candidats', description: 'Connectez-vous avec un compte candidat.', variant: 'destructive' });
      return;
    }
    setMatchResult(null);
    setMatchOpen(true);
    setMatchLoading(true);
    try {
      setMatchResult(await aiService.matchJob(job.id));
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
      setMatchOpen(false);
    } finally {
      setMatchLoading(false);
    }
  };

  useJobSeo(job);

  useEffect(() => {
    setLoading(true);
    setNotFound(false);
    jobService.getJobById(jobId)
      .then((data) => setJob(data))
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
    window.scrollTo(0, 0);
  }, [jobId]);

  useEffect(() => {
    if (job && isAuthenticated && isCandidate) {
      savedJobService.checkJobSaved(job.id).then(setIsSaved).catch(() => {});
    }
  }, [job, isAuthenticated, isCandidate]);

  const formatSalary = () => {
    if (!job) return null;
    if (job.salary_min && job.salary_max) {
      return `${job.salary_min.toLocaleString('fr-FR')} - ${job.salary_max.toLocaleString('fr-FR')} € par an`;
    }
    if (job.salary_min) return `À partir de ${job.salary_min.toLocaleString('fr-FR')} € par an`;
    return null;
  };

  const handleApply = async () => {
    if (job.is_partner && job.external_url) {
      try {
        const { redirect_url } = await jobService.recordClick(job.id);
        window.open(redirect_url || job.external_url, '_blank');
      } catch {
        window.open(job.external_url, '_blank');
      }
      return;
    }
    if (!isAuthenticated) { setShowAuthModal(true); return; }
    if (!isCandidate) {
      toast({ title: 'Accès refusé', description: 'Seuls les candidats peuvent postuler', variant: 'destructive' });
      return;
    }
    setShowApplyModal(true);
  };

  const handleSave = async () => {
    if (!isAuthenticated) { setShowAuthModal(true); return; }
    if (!isCandidate) {
      toast({ title: 'Accès refusé', description: 'Seuls les candidats peuvent sauvegarder', variant: 'destructive' });
      return;
    }
    setSavingJob(true);
    try {
      if (isSaved) {
        await savedJobService.unsaveJob(job.id); setIsSaved(false);
        toast({ title: 'Offre retirée de vos favoris' });
      } else {
        await savedJobService.saveJob(job.id); setIsSaved(true);
        toast({ title: 'Offre sauvegardée' });
      }
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    } finally {
      setSavingJob(false);
    }
  };

  const shareUrl = typeof window !== 'undefined' ? window.location.href : '';
  const shareText = job ? `${job.title} chez ${job.company?.name} — Joboolo` : 'Offre Joboolo';

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast({ title: 'Lien copié', description: 'Partagez cette offre où vous voulez !' });
    } catch {
      toast({ title: 'Erreur', description: 'Impossible de copier le lien', variant: 'destructive' });
    }
  };

  const shareLinks = {
    linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`,
    twitter: `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(shareUrl)}`,
    email: `mailto:?subject=${encodeURIComponent(shareText)}&body=${encodeURIComponent(shareUrl)}`,
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-5xl mx-auto px-4 py-16 text-center text-gray-500" data-testid="job-detail-loading">
          Chargement de l'offre...
        </div>
        <Footer />
      </div>
    );
  }

  if (notFound || !job) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-5xl mx-auto px-4 py-16 text-center" data-testid="job-detail-notfound">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">Offre introuvable</h1>
          <p className="text-gray-600 mb-6">Cette offre n'existe plus ou a été retirée.</p>
          <Button onClick={() => navigate('/')} data-testid="job-detail-back-home">Voir toutes les offres</Button>
        </div>
        <Footer />
      </div>
    );
  }

  const salary = formatSalary();

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="job-detail-page">
        {/* Breadcrumb */}
        <nav className="flex items-center text-sm text-gray-500 mb-6 flex-wrap gap-1">
          <Link to="/" className="hover:text-brand">Accueil</Link>
          <ChevronRight className="h-4 w-4" />
          <Link to="/" className="hover:text-brand">Offres d'emploi</Link>
          <ChevronRight className="h-4 w-4" />
          <span className="text-gray-900 font-medium truncate max-w-[220px]">{job.title}</span>
        </nav>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Main content */}
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardContent className="p-6">
                <div className="flex items-start gap-2 flex-wrap mb-3">
                  <h1 className="text-3xl font-bold text-gray-900" data-testid="job-detail-title">{job.title}</h1>
                  {job.is_new && <Badge className="bg-green-100 text-green-800">Nouveau</Badge>}
                  {job.is_urgent && <Badge className="bg-red-100 text-red-800">Urgent</Badge>}
                </div>

                <div className="flex items-center text-gray-600 mb-2">
                  <Building className="h-4 w-4 mr-1" />
                  <span className="mr-4 font-medium" data-testid="job-detail-company">{job.company?.name}</span>
                  <MapPin className="h-4 w-4 mr-1" />
                  <span>{job.location}</span>
                </div>

                <div className="flex items-center gap-3 flex-wrap mb-4">
                  <Badge variant="outline">{job.job_type}</Badge>
                  {job.is_remote && <Badge variant="outline" className="bg-brand/10 text-brand">Télétravail</Badge>}
                  <span className="flex items-center text-sm text-gray-500">
                    <Clock className="h-4 w-4 mr-1" />
                    {new Date(job.created_at).toLocaleDateString('fr-FR')}
                  </span>
                  <span className="text-sm text-gray-400">{job.views_count} vues</span>
                </div>

                {salary && (
                  <div className="flex items-center text-brand font-semibold mb-2">
                    <Euro className="h-5 w-5 mr-1" />
                    <span data-testid="job-detail-salary">{salary}</span>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-3">Description du poste</h2>
                <p className="text-gray-700 whitespace-pre-line leading-relaxed" data-testid="job-detail-description">
                  {job.description}
                </p>

                {job.requirements?.length > 0 && (
                  <div className="mt-6">
                    <h3 className="font-semibold text-gray-900 mb-2">Profil recherché</h3>
                    <ul className="space-y-2">
                      {job.requirements.map((r, i) => (
                        <li key={i} className="flex items-start text-gray-700">
                          <CheckCircle2 className="h-4 w-4 text-green-600 mr-2 mt-1 shrink-0" />{r}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {job.benefits?.length > 0 && (
                  <div className="mt-6">
                    <h3 className="font-semibold text-gray-900 mb-2">Avantages</h3>
                    <ul className="space-y-2">
                      {job.benefits.map((b, i) => (
                        <li key={i} className="flex items-start text-gray-700">
                          <Gift className="h-4 w-4 text-brand mr-2 mt-1 shrink-0" />{b}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {job.tags?.length > 0 && (
                  <div className="mt-6 flex flex-wrap gap-2">
                    {job.tags.map((t, i) => (
                      <Badge key={i} variant="secondary">{t}</Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            <Card className="lg:sticky lg:top-24">
              <CardContent className="p-6 space-y-3">
                <Button
                  className="w-full bg-brand hover:bg-brand-hover h-12 text-base"
                  onClick={handleApply}
                  disabled={applying}
                  data-testid="job-detail-apply-btn"
                >
                  {applying ? 'Envoi...' : 'Postuler maintenant'}
                </Button>
                <Button
                  variant="outline"
                  className={`w-full text-red-600 border-red-200 hover:bg-red-50 ${isSaved ? 'bg-red-50' : ''}`}
                  onClick={handleSave}
                  disabled={savingJob}
                  data-testid="job-detail-save-btn"
                >
                  <Heart className={`h-4 w-4 mr-2 ${isSaved ? 'fill-current' : ''}`} />
                  {isSaved ? 'Sauvegardée' : 'Sauvegarder'}
                </Button>
                {!job.is_partner && (
                  <Button
                    variant="outline"
                    className="w-full border-brand/30 text-brand hover:bg-brand-50"
                    onClick={handleAnalyze}
                    data-testid="job-detail-analyze-btn"
                  >
                    <Sparkles className="h-4 w-4 mr-2" />Analyser ma compatibilité (IA)
                  </Button>
                )}

                <div className="pt-4 border-t">
                  <p className="flex items-center text-sm font-medium text-gray-700 mb-3">
                    <Share2 className="h-4 w-4 mr-2" />Partager cette offre
                  </p>
                  <div className="grid grid-cols-4 gap-2">
                    <button onClick={copyLink} title="Copier le lien" data-testid="job-detail-share-copy"
                      className="flex items-center justify-center h-10 rounded-md border hover:bg-gray-50 transition-colors">
                      <LinkIcon className="h-4 w-4 text-gray-600" />
                    </button>
                    <a href={shareLinks.linkedin} target="_blank" rel="noopener noreferrer" title="LinkedIn" data-testid="job-detail-share-linkedin"
                      className="flex items-center justify-center h-10 rounded-md border hover:bg-gray-50 transition-colors">
                      <Linkedin className="h-4 w-4 text-[#0A66C2]" />
                    </a>
                    <a href={shareLinks.twitter} target="_blank" rel="noopener noreferrer" title="X (Twitter)" data-testid="job-detail-share-twitter"
                      className="flex items-center justify-center h-10 rounded-md border hover:bg-gray-50 transition-colors">
                      <Twitter className="h-4 w-4 text-gray-800" />
                    </a>
                    <a href={shareLinks.email} title="Email" data-testid="job-detail-share-email"
                      className="flex items-center justify-center h-10 rounded-md border hover:bg-gray-50 transition-colors">
                      <Mail className="h-4 w-4 text-gray-600" />
                    </a>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Button variant="ghost" onClick={() => navigate('/')} className="text-gray-600" data-testid="job-detail-back-btn">
              <ArrowLeft className="h-4 w-4 mr-2" />Retour aux offres
            </Button>
          </div>
        </div>
      </div>

      <Footer />
      <AuthModal isOpen={showAuthModal} onClose={() => setShowAuthModal(false)} />
      <ApplyModal isOpen={showApplyModal} onClose={() => setShowApplyModal(false)} job={job} />
      <MatchDialog open={matchOpen} onOpenChange={setMatchOpen} loading={matchLoading} result={matchResult} title="Ma compatibilité avec l'offre" />
    </div>
  );
};

export default JobDetail;
