import React, { useState, useEffect } from 'react';
import { Card } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { MapPin, Building, Clock, Euro, Heart } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { applicationService } from '../services/applicationService';
import { jobService } from '../services/jobService';
import { savedJobService } from '../services/savedJobService';
import { useToast } from '../hooks/use-toast';
import AuthModal from './AuthModal';
import ApplyModal from './ApplyModal';

const JobCard = ({ job }) => {
  const { user, isAuthenticated, isCandidate } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [applying, setApplying] = useState(false);
  const [isSaved, setIsSaved] = useState(false);
  const [savingJob, setSavingJob] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [showApplyModal, setShowApplyModal] = useState(false);

  // Check if job is saved on component mount
  useEffect(() => {
    if (isAuthenticated && isCandidate) {
      checkJobSaved();
    }
  }, [job.id, isAuthenticated, isCandidate]);

  const checkJobSaved = async () => {
    try {
      const saved = await savedJobService.checkJobSaved(job.id);
      setIsSaved(saved);
    } catch (error) {
      // Silently fail - not critical
    }
  };

  const formatSalary = () => {
    if (job.salary_min && job.salary_max) {
      return `${job.salary_min.toLocaleString()} - ${job.salary_max.toLocaleString()} € par an`;
    } else if (job.salary_min) {
      return `À partir de ${job.salary_min.toLocaleString()} € par an`;
    }
    return null;
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffTime = Math.abs(now - date);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 1) return "Il y a 1 jour";
    if (diffDays < 7) return `Il y a ${diffDays} jours`;
    if (diffDays < 14) return "Il y a 1 semaine";
    return `Il y a ${Math.floor(diffDays / 7)} semaines`;
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
    if (!isAuthenticated) {
      setShowAuthModal(true);
      return;
    }

    if (!isCandidate) {
      toast({
        title: "Accès refusé",
        description: "Seuls les candidats peuvent postuler aux offres",
        variant: "destructive",
      });
      return;
    }

    setShowApplyModal(true);
  };

  const handleSaveJob = async () => {
    if (!isAuthenticated) {
      setShowAuthModal(true);
      return;
    }

    if (!isCandidate) {
      toast({
        title: "Accès refusé",
        description: "Seuls les candidats peuvent sauvegarder des offres",
        variant: "destructive",
      });
      return;
    }

    setSavingJob(true);
    try {
      if (isSaved) {
        await savedJobService.unsaveJob(job.id);
        setIsSaved(false);
        toast({
          title: "Offre retirée",
          description: "L'offre a été retirée de vos favoris",
        });
      } else {
        await savedJobService.saveJob(job.id);
        setIsSaved(true);
        toast({
          title: "Offre sauvegardée",
          description: "L'offre a été ajoutée à vos favoris",
        });
      }
    } catch (error) {
      toast({
        title: "Erreur",
        description: error.message,
        variant: "destructive",
      });
    } finally {
      setSavingJob(false);
    }
  };

  const salary = formatSalary();
  const companyInitial = (job.company?.name || '?').charAt(0).toUpperCase();

  return (
    <>
      <Card
        className="group p-6 rounded-2xl border border-slate-200 bg-white transition-all duration-300 hover:-translate-y-1 hover:shadow-lg hover:shadow-slate-200/60 hover:border-brand/30 cursor-pointer"
        onClick={() => navigate(`/jobs/${job.id}`)}
        data-testid={`job-card-${job.id}`}
      >
        <div className="flex items-start gap-4">
          {/* Company logo mark */}
          <div className="hidden sm:flex shrink-0 h-12 w-12 items-center justify-center rounded-xl bg-brand/10 text-brand font-heading font-bold text-lg">
            {companyInitial}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3
                  className="font-heading text-xl font-semibold text-slate-900 group-hover:text-brand transition-colors truncate"
                  onClick={(e) => { e.stopPropagation(); navigate(`/jobs/${job.id}`); }}
                  data-testid={`job-card-title-${job.id}`}
                >
                  {job.title}
                </h3>
                <div className="flex items-center flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500 mt-1">
                  <span className="inline-flex items-center font-medium text-slate-700">
                    <Building className="h-4 w-4 mr-1" />{job.company.name}
                  </span>
                  <span className="inline-flex items-center">
                    <MapPin className="h-4 w-4 mr-1" />{job.location}
                  </span>
                  <span className="inline-flex items-center text-slate-400">
                    <Clock className="h-4 w-4 mr-1" />{formatDate(job.created_at)}
                  </span>
                </div>
              </div>

              <button
                onClick={(e) => { e.stopPropagation(); handleSaveJob(); }}
                disabled={savingJob}
                aria-label={isSaved ? 'Retirer des favoris' : 'Sauvegarder'}
                className={`shrink-0 h-9 w-9 flex items-center justify-center rounded-full border transition-colors ${isSaved ? 'border-rose-200 bg-rose-50 text-rose-500' : 'border-slate-200 text-slate-400 hover:text-rose-500 hover:border-rose-200'}`}
                data-testid={`job-card-save-${job.id}`}
              >
                <Heart className={`h-4 w-4 ${isSaved ? 'fill-current' : ''}`} />
              </button>
            </div>

            {/* Badges */}
            <div className="flex items-center flex-wrap gap-2 mt-3">
              <Badge className="rounded-full bg-slate-100 text-slate-700 hover:bg-slate-100 text-[11px] uppercase tracking-widest font-semibold">
                {job.job_type}
              </Badge>
              {job.is_remote && (
                <Badge className="rounded-full bg-emerald-50 text-emerald-700 hover:bg-emerald-50 text-[11px] uppercase tracking-widest font-semibold">
                  Télétravail
                </Badge>
              )}
              {job.is_new && (
                <Badge className="rounded-full bg-brand/10 text-brand hover:bg-brand/10 text-[11px] uppercase tracking-widest font-semibold">
                  Nouveau
                </Badge>
              )}
              {job.is_urgent && (
                <Badge className="rounded-full bg-rose-50 text-rose-600 hover:bg-rose-50 text-[11px] uppercase tracking-widest font-semibold">
                  Urgent
                </Badge>
              )}
            </div>

            {salary && (
              <div className="flex items-center text-sm font-semibold text-slate-900 mt-3">
                <Euro className="h-4 w-4 mr-1 text-brand" />{salary}
              </div>
            )}

            <p className="text-slate-500 text-sm line-clamp-2 mt-3 leading-relaxed">
              {job.description}
            </p>

            <div className="flex items-center justify-between pt-4 mt-4 border-t border-slate-100">
              {job.logo_url ? (
                <img
                  src={`${process.env.REACT_APP_BACKEND_URL}${job.logo_url}`}
                  alt={job.company?.name || 'logo'}
                  className="h-9 max-w-[130px] object-contain"
                  onClick={(e) => e.stopPropagation()}
                  data-testid={`job-card-logo-${job.id}`}
                />
              ) : (
                <span />
              )}
              <Button
                onClick={(e) => { e.stopPropagation(); handleApply(); }}
                disabled={applying}
                className="rounded-full bg-brand hover:bg-brand-hover text-white px-6 transition-transform active:scale-95"
                data-testid={`job-card-apply-${job.id}`}
              >
                Postuler
              </Button>
            </div>
          </div>
        </div>
      </Card>

      <AuthModal isOpen={showAuthModal} onClose={() => setShowAuthModal(false)} />
      <ApplyModal isOpen={showApplyModal} onClose={() => setShowApplyModal(false)} job={job} />
    </>
  );
};

export default JobCard;