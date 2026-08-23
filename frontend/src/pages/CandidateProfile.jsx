import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../hooks/use-toast';
import { useNavigate } from 'react-router-dom';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Separator } from '../components/ui/separator';
import { User, Briefcase, Edit, Save, X, Plus, MapPin, Bell, Heart, History, Search, FileText, ChevronRight, Camera, Link as LinkIcon, Mail } from 'lucide-react';
import AutocompleteInput from '../components/AutocompleteInput';
import CandidateDocuments from '../components/CandidateDocuments';
import { applicationService } from '../services/applicationService';
import { savedJobService } from '../services/savedJobService';
import { alertService } from '../services/alertService';
import { fileService } from '../services/fileService';
import { getHistory } from '../utils/searchHistory';

const CandidateProfile = () => {
  const { user, isAuthenticated, updateProfile } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [applications, setApplications] = useState([]);
  const [savedJobs, setSavedJobs] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [savedSearches, setSavedSearches] = useState([]);
  const [cvCount, setCvCount] = useState(0);
  const [coverCount, setCoverCount] = useState(0);
  
  const [profileData, setProfileData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    location: '',
    bio: '',
    skills: [],
    experience_years: 0,
    profile_photo_url: '',
    social_link_1: '',
    social_link_2: '',
    social_link_3: '',
  });

  const [newSkill, setNewSkill] = useState('');
  const [uploadingPhoto, setUploadingPhoto] = useState(false);

  useEffect(() => {
    if (user) {
      setProfileData({
        first_name: user.first_name || '',
        last_name: user.last_name || '',
        email: user.email || '',
        phone: user.phone || '',
        location: user.location || '',
        bio: user.bio || '',
        skills: user.skills || [],
        experience_years: user.experience_years || 0,
        profile_photo_url: user.profile_photo_url || '',
        social_link_1: user.social_link_1 || '',
        social_link_2: user.social_link_2 || '',
        social_link_3: user.social_link_3 || '',
      });
      // Load real stats (best-effort, silent errors)
      applicationService.getMyApplications().then((r) => setApplications(r || [])).catch(() => setApplications([]));
      savedJobService.getSavedJobs().then((r) => setSavedJobs(r || [])).catch(() => setSavedJobs([]));
      alertService.getMyAlerts().then((r) => setAlerts(r || [])).catch(() => setAlerts([]));
      fileService.listCandidateDocuments().then((list) => {
        const arr = list || [];
        setCvCount(arr.filter((d) => d.category === 'cv').length);
        setCoverCount(arr.filter((d) => d.category === 'cover_letter').length);
      }).catch(() => {});
      setSavedSearches(getHistory() || []);
    }
  }, [user]);

  // Refresh saved-searches count when localStorage changes
  useEffect(() => {
    const refresh = () => setSavedSearches(getHistory() || []);
    window.addEventListener('joboolo-history-changed', refresh);
    return () => window.removeEventListener('joboolo-history-changed', refresh);
  }, []);

  // Compute a real profile completion % based on filled fields
  const computeCompletion = () => {
    const fields = [
      profileData.first_name,
      profileData.last_name,
      profileData.email,
      profileData.phone,
      profileData.location,
      profileData.bio,
      (profileData.skills || []).length > 0 ? 'ok' : '',
      profileData.experience_years > 0 ? 'ok' : '',
    ];
    const filled = fields.filter((v) => v && String(v).trim() !== '').length;
    return Math.round((filled / fields.length) * 100);
  };
  const completion = computeCompletion();
  const activeAlerts = alerts.filter((a) => a?.is_active !== false).length;
  const pendingApps = applications.filter((a) => (a?.status || 'pending') === 'pending').length;

  const quickActions = [
    { label: 'Rechercher des emplois', icon: Search, to: '/', testid: 'action-search' },
    { label: 'Mes candidatures', icon: FileText, to: '/my-applications', count: applications.length, testid: 'action-applications' },
    { label: 'Mes CV', icon: FileText, to: '/my-cv', count: cvCount, testid: 'action-cv' },
    { label: 'Mes lettres de motivation', icon: Mail, to: '/my-cover-letters', count: coverCount, testid: 'action-cover-letters' },
    { label: 'Mes alertes', icon: Bell, to: '/my-alerts', count: activeAlerts, testid: 'action-alerts' },
    { label: 'Emplois sauvegardés', icon: Heart, to: '/saved-jobs', count: savedJobs.length, testid: 'action-saved-jobs' },
    { label: 'Recherches sauvegardées', icon: History, to: '/saved-searches', count: savedSearches.length, testid: 'action-saved-searches' },
    { label: 'Modifier mon profil', icon: Edit, action: () => setIsEditing(true), testid: 'action-edit-profile' },
  ];
  const runAction = (a) => (a.action ? a.action() : navigate(a.to));

  const handleSave = async () => {
    setLoading(true);
    try {
      const result = await updateProfile({
        first_name: profileData.first_name,
        last_name: profileData.last_name,
        phone: profileData.phone,
        location: profileData.location,
        bio: profileData.bio,
        skills: profileData.skills,
        experience_years: profileData.experience_years,
        social_link_1: profileData.social_link_1,
        social_link_2: profileData.social_link_2,
        social_link_3: profileData.social_link_3,
      });

      if (result.success) {
        toast({
          title: "Profil mis à jour",
          description: "Vos informations ont été sauvegardées avec succès",
        });
        setIsEditing(false);
      } else {
        throw new Error(result.error);
      }
    } catch (error) {
      toast({
        title: "Erreur",
        description: error.message || "Impossible de sauvegarder le profil",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const handlePhotoChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingPhoto(true);
    try {
      const res = await fileService.uploadProfilePhoto(file);
      setProfileData((p) => ({ ...p, profile_photo_url: res.profile_photo_url }));
      // Persist on the user doc via /auth/me so Header + counts pick it up
      await updateProfile({ profile_photo_url: res.profile_photo_url });
      toast({ title: 'Photo mise à jour' });
    } catch (err) {
      toast({ title: 'Erreur', description: err.message, variant: 'destructive' });
    } finally {
      setUploadingPhoto(false);
      e.target.value = '';
    }
  };

  const addSkill = () => {
    if (newSkill.trim() && !profileData.skills.includes(newSkill.trim())) {
      setProfileData(prev => ({
        ...prev,
        skills: [...prev.skills, newSkill.trim()]
      }));
      setNewSkill('');
    }
  };

  const removeSkill = (skillToRemove) => {
    setProfileData(prev => ({
      ...prev,
      skills: prev.skills.filter(skill => skill !== skillToRemove)
    }));
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'pending': return 'bg-yellow-100 text-yellow-800';
      case 'reviewed': return 'bg-blue-100 text-blue-800';
      case 'accepted': return 'bg-green-100 text-green-800';
      case 'rejected': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusText = (status) => {
    switch (status) {
      case 'pending': return 'En attente';
      case 'reviewed': return 'Examiné';
      case 'accepted': return 'Accepté';
      case 'rejected': return 'Refusé';
      default: return status;
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">
            Accès refusé
          </h1>
          <p className="text-slate-500">
            Vous devez être connecté pour accéder à cette page.
          </p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Onglets rapides (reprennent les actions rapides) */}
        <div className="mb-6 -mx-1 overflow-x-auto pb-1" data-testid="profile-tabs">
          <div className="flex gap-2 px-1 min-w-max">
            {quickActions.map((a) => (
              <button
                key={a.testid}
                onClick={() => runAction(a)}
                data-testid={`tab-${a.testid}`}
                className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:border-brand hover:text-brand transition-colors"
              >
                <a.icon className="h-4 w-4" />{a.label}
                {a.count > 0 && <span className="ml-0.5 text-xs bg-brand/10 text-brand rounded-full px-1.5 py-0.5">{a.count}</span>}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          
          {/* Profile Information */}
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="flex items-center space-x-2">
                  <User className="h-5 w-5" />
                  <span>Informations personnelles</span>
                </CardTitle>
                <Button
                  variant={isEditing ? "destructive" : "outline"}
                  size="sm"
                  onClick={() => {
                    if (isEditing) {
                    setIsEditing(false);
                    // Reset to original data
                    setProfileData({
                      first_name: user.first_name || '',
                      last_name: user.last_name || '',
                      email: user.email || '',
                      phone: user.phone || '',
                      location: user.location || '',
                      bio: user.bio || '',
                      skills: user.skills || [],
                      experience_years: user.experience_years || 0,
                      profile_photo_url: user.profile_photo_url || '',
                      social_link_1: user.social_link_1 || '',
                      social_link_2: user.social_link_2 || '',
                      social_link_3: user.social_link_3 || '',
                    });
                  } else {
                    setIsEditing(true);
                  }
                  }}
                >
                  {isEditing ? <X className="h-4 w-4 mr-2" /> : <Edit className="h-4 w-4 mr-2" />}
                  {isEditing ? 'Annuler' : 'Modifier'}
                </Button>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Profile photo + upload */}
                <div className="flex items-center gap-4">
                  <div className="relative">
                    <div className="h-20 w-20 rounded-full bg-slate-100 flex items-center justify-center overflow-hidden ring-2 ring-white shadow" data-testid="profile-photo">
                      {profileData.profile_photo_url ? (
                        <img src={profileData.profile_photo_url} alt="profil" className="h-full w-full object-cover" />
                      ) : (
                        <User className="h-10 w-10 text-slate-300" />
                      )}
                    </div>
                    <label htmlFor="profile-photo-input" className="absolute -bottom-1 -right-1 h-8 w-8 rounded-full bg-brand text-white flex items-center justify-center shadow cursor-pointer hover:bg-brand-hover" title="Changer la photo">
                      <Camera className="h-4 w-4" />
                    </label>
                    <input
                      id="profile-photo-input"
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={handlePhotoChange}
                      data-testid="profile-photo-input"
                    />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-slate-800">Photo de profil</p>
                    <p className="text-xs text-slate-400">JPG, PNG, WEBP ou GIF — max 3 Mo.</p>
                    {uploadingPhoto && <p className="text-xs text-brand mt-1">Envoi en cours…</p>}
                  </div>
                </div>
                <Separator />

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="first_name">Prénom</Label>
                    <Input
                      id="first_name"
                      value={profileData.first_name}
                      onChange={(e) => setProfileData(prev => ({...prev, first_name: e.target.value}))}
                      disabled={!isEditing}
                    />
                  </div>
                  <div>
                    <Label htmlFor="last_name">Nom</Label>
                    <Input
                      id="last_name"
                      value={profileData.last_name}
                      onChange={(e) => setProfileData(prev => ({...prev, last_name: e.target.value}))}
                      disabled={!isEditing}
                    />
                  </div>
                </div>

                <div>
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={profileData.email}
                    disabled={true}
                    className="bg-gray-100"
                  />
                  <p className="text-xs text-slate-400 mt-1">L'email ne peut pas être modifié</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="phone">Téléphone</Label>
                    <Input
                      id="phone"
                      value={profileData.phone}
                      onChange={(e) => setProfileData(prev => ({...prev, phone: e.target.value}))}
                      disabled={!isEditing}
                      placeholder="+33 6 12 34 56 78"
                    />
                  </div>
                  <div>
                    <Label htmlFor="location">Localisation</Label>
                    {isEditing ? (
                      <AutocompleteInput
                        value={profileData.location}
                        onChange={(v) => setProfileData(prev => ({ ...prev, location: v }))}
                        field="location"
                        icon={MapPin}
                        placeholder="Ville, département ou région"
                        testId="profile-location"
                        inputClassName="w-full h-10 pl-10 pr-3 py-2 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1"
                      />
                    ) : (
                      <Input id="location" value={profileData.location} disabled placeholder="Non renseignée" />
                    )}
                  </div>
                </div>

                <div>
                  <Label htmlFor="experience_years">Années d'expérience</Label>
                  <Input
                    id="experience_years"
                    type="number"
                    min="0"
                    value={profileData.experience_years}
                    onChange={(e) => setProfileData(prev => ({...prev, experience_years: parseInt(e.target.value) || 0}))}
                    disabled={!isEditing}
                  />
                </div>

                <div>
                  <Label htmlFor="bio">À propos de moi</Label>
                  <Textarea
                    id="bio"
                    value={profileData.bio}
                    onChange={(e) => setProfileData(prev => ({...prev, bio: e.target.value}))}
                    disabled={!isEditing}
                    placeholder="Parlez-nous de vous, vos passions, votre parcours..."
                    rows={4}
                  />
                </div>

                {/* Social links */}
                <div>
                  <Label className="flex items-center gap-1.5"><LinkIcon className="h-4 w-4 text-slate-500" />Mes sites et liens sociaux : LinkedIn, GitHub, Portfolio, etc..</Label>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-2">
                    <Input
                      value={profileData.social_link_1}
                      onChange={(e) => setProfileData((p) => ({ ...p, social_link_1: e.target.value }))}
                      disabled={!isEditing}
                      placeholder="https://linkedin.com/in/votreprofil"
                      data-testid="social-link-1"
                    />
                    <Input
                      value={profileData.social_link_2}
                      onChange={(e) => setProfileData((p) => ({ ...p, social_link_2: e.target.value }))}
                      disabled={!isEditing}
                      placeholder="https://github.com/votreprofil"
                      data-testid="social-link-2"
                    />
                    <Input
                      value={profileData.social_link_3}
                      onChange={(e) => setProfileData((p) => ({ ...p, social_link_3: e.target.value }))}
                      disabled={!isEditing}
                      placeholder="https://mon-portfolio.dev"
                      data-testid="social-link-3"
                    />
                  </div>
                  {!isEditing && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {[profileData.social_link_1, profileData.social_link_2, profileData.social_link_3]
                        .filter((v) => v && v.trim())
                        .map((v, i) => (
                          <a key={i} href={v} target="_blank" rel="noopener noreferrer" className="text-xs px-2.5 py-1 rounded-full bg-brand/10 text-brand hover:bg-brand/20 truncate max-w-[240px]">
                            {v.replace(/^https?:\/\//, '')}
                          </a>
                        ))}
                    </div>
                  )}
                </div>

                {/* Skills Section */}
                <div>
                  <Label>Compétences</Label>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {profileData.skills.map((skill, index) => (
                      <Badge key={index} variant="secondary" className="flex items-center space-x-1">
                        <span>{skill}</span>
                        {isEditing && (
                          <button
                            onClick={() => removeSkill(skill)}
                            className="ml-1 text-red-500 hover:text-red-700"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        )}
                      </Badge>
                    ))}
                  </div>
                  
                  {isEditing && (
                    <div className="flex space-x-2">
                      <Input
                        value={newSkill}
                        onChange={(e) => setNewSkill(e.target.value)}
                        placeholder="Ajouter une compétence"
                        onKeyPress={(e) => e.key === 'Enter' && addSkill()}
                      />
                      <Button onClick={addSkill} size="sm">
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>

                {isEditing && (
                  <div className="flex justify-end space-x-2 pt-4">
                    <Button
                      variant="outline"
                      onClick={() => setIsEditing(false)}
                    >
                      Annuler
                    </Button>
                    <Button
                      onClick={handleSave}
                      disabled={loading}
                    >
                      {loading ? (
                        <>Sauvegarde...</>
                      ) : (
                        <>
                          <Save className="h-4 w-4 mr-2" />
                          Sauvegarder
                        </>
                      )}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Candidate documents — CV + Cover letters (max 3 each) */}
            <CandidateDocuments />
          </div>

          {/* Sidebar with stats and quick actions */}
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center space-x-2">
                  <Briefcase className="h-5 w-5" />
                  <span>Mes statistiques</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1" data-testid="profile-stats">
                  <button onClick={() => navigate('/my-applications')} className="w-full flex justify-between items-center py-1.5 group text-left" data-testid="stat-applications-link">
                    <span className="text-slate-500 group-hover:text-brand transition-colors">Candidatures envoyées</span>
                    <span className="flex items-center gap-1"><Badge variant="secondary" data-testid="stat-applications">{applications.length}</Badge><ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-brand" /></span>
                  </button>
                  <button onClick={() => navigate('/my-applications')} className="w-full flex justify-between items-center py-1.5 group text-left" data-testid="stat-applications-pending-link">
                    <span className="text-slate-500 group-hover:text-brand transition-colors">Candidatures en attente</span>
                    <span className="flex items-center gap-1"><Badge variant="secondary" data-testid="stat-applications-pending">{pendingApps}</Badge><ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-brand" /></span>
                  </button>
                  <button onClick={() => navigate('/my-cv')} className="w-full flex justify-between items-center py-1.5 group text-left" data-testid="stat-cv-link">
                    <span className="text-slate-500 group-hover:text-brand transition-colors">Mes CV</span>
                    <span className="flex items-center gap-1"><Badge variant="secondary" data-testid="stat-cv">{cvCount}</Badge><ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-brand" /></span>
                  </button>
                  <button onClick={() => navigate('/my-cover-letters')} className="w-full flex justify-between items-center py-1.5 group text-left" data-testid="stat-cover-letters-link">
                    <span className="text-slate-500 group-hover:text-brand transition-colors">Mes lettres de motivation</span>
                    <span className="flex items-center gap-1"><Badge variant="secondary" data-testid="stat-cover-letters">{coverCount}</Badge><ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-brand" /></span>
                  </button>
                  <button onClick={() => navigate('/saved-jobs')} className="w-full flex justify-between items-center py-1.5 group text-left" data-testid="stat-saved-link">
                    <span className="text-slate-500 group-hover:text-brand transition-colors">Emplois sauvegardés</span>
                    <span className="flex items-center gap-1"><Badge variant="secondary" data-testid="stat-saved">{savedJobs.length}</Badge><ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-brand" /></span>
                  </button>
                  <button onClick={() => navigate('/my-alerts')} className="w-full flex justify-between items-center py-1.5 group text-left" data-testid="stat-alerts-link">
                    <span className="text-slate-500 group-hover:text-brand transition-colors">Alertes actives</span>
                    <span className="flex items-center gap-1"><Badge variant="secondary" data-testid="stat-alerts">{activeAlerts}</Badge><ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-brand" /></span>
                  </button>
                  <button onClick={() => navigate('/saved-searches')} className="w-full flex justify-between items-center py-1.5 group text-left" data-testid="stat-searches-link">
                    <span className="text-slate-500 group-hover:text-brand transition-colors">Recherches sauvegardées</span>
                    <span className="flex items-center gap-1"><Badge variant="secondary" data-testid="stat-searches">{savedSearches.length}</Badge><ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-brand" /></span>
                  </button>
                  <Separator />
                  <div>
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-slate-500">Profil complété</span>
                      <Badge variant="secondary" data-testid="stat-completion">{completion}%</Badge>
                    </div>
                    <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                      <div className="h-full bg-brand transition-all" style={{ width: `${completion}%` }} />
                    </div>
                    {completion < 100 && (
                      <button
                        onClick={() => setIsEditing(true)}
                        className="mt-2 text-xs text-brand hover:underline"
                        data-testid="complete-profile-btn"
                      >
                        Compléter mon profil
                      </button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Actions rapides</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2" data-testid="quick-actions">
                {quickActions.map((a) => (
                  <Button
                    key={a.testid}
                    className="w-full justify-between group"
                    variant="outline"
                    onClick={() => runAction(a)}
                    data-testid={a.testid}
                  >
                    <span className="flex items-center"><a.icon className="h-4 w-4 mr-2" />{a.label}{a.count > 0 ? ` (${a.count})` : ''}</span>
                    <ChevronRight className="h-4 w-4 opacity-40 group-hover:opacity-100" />
                  </Button>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      <Footer />
    </div>
  );
};

export default CandidateProfile;