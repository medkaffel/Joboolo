import React, { useState, useEffect } from 'react';
import { Button } from './ui/button';
import { Menu, User, FileText, Heart, Briefcase, Plus, LogOut, ChevronDown, Bell, History, Mail, Sparkles, MessageSquare, BarChart3 } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from './ui/dropdown-menu';
import { useAuth } from '../contexts/AuthContext';
import { messageService } from '../services/messageService';
import AuthModal from './AuthModal';
import { useNavigate } from 'react-router-dom';

const ALL_NAV_LINKS = [
  { label: 'Rechercher des emplois', to: '/' },
  { label: 'Recruteur', to: '/recruteur' },
  { label: 'Partenaire', to: '/partenaire' },
  { label: 'Affiliation', to: '#' },
];

const Header = () => {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const { user, logout, isAuthenticated, isEmployer, isCandidate } = useAuth();
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!isAuthenticated) { setUnread(0); return; }
    let active = true;
    const poll = () => messageService.unreadCount().then((n) => { if (active) setUnread(n); });
    poll();
    const t = setInterval(poll, 15000);
    return () => { active = false; clearInterval(t); };
  }, [isAuthenticated]);

  // Filtrage des liens du menu principal selon le rôle :
  // - Candidat  : uniquement « Rechercher des emplois »
  // - Recruteur / Admin : aucun lien
  // - Anonyme / Partenaire : tous les liens
  const NAV_LINKS = isEmployer
    ? []
    : isCandidate
      ? ALL_NAV_LINKS.filter((l) => l.label === 'Rechercher des emplois')
      : ALL_NAV_LINKS;

  const handleProfileClick = () => {
    if (user?.user_type === 'candidate') navigate('/profile');
    else navigate('/employer-dashboard');
  };

  const handleNav = (link) => {
    if (link.label === 'Partenaire') {
      if (isAuthenticated && user?.user_type === 'partner') navigate('/partenaire');
      else setIsAuthOpen(true);
      return;
    }
    navigate(link.to);
  };

  return (
    <>
      <header className="sticky top-0 z-50 backdrop-blur-xl bg-white/80 border-b border-slate-200/60">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-20">
            {/* Logo */}
            <button
              className="flex items-center gap-1.5 cursor-pointer"
              onClick={() => navigate('/')}
              data-testid="logo-home-btn"
            >
              <span className="font-heading text-2xl sm:text-2xl lg:text-3xl font-extrabold tracking-tight text-slate-900 leading-none">
                Job<span className="text-brand">oolo</span>
              </span>
            </button>

            {/* Desktop Navigation */}
            <nav className="hidden md:flex items-center gap-8">
              {NAV_LINKS.map((l) => (
                <button
                  key={l.label}
                  onClick={() => handleNav(l)}
                  className="text-sm font-medium text-slate-600 hover:text-brand transition-colors"
                  data-testid={`nav-${l.label === 'Partenaire' ? 'partenaire' : l.to.replace(/[/#]/g, '') || 'home'}`}
                >
                  {l.label}
                </button>
              ))}
            </nav>

            {/* Right Section */}
            <div className="flex items-center gap-3">
              {isEmployer && (
                <button
                  onClick={() => navigate('/post-job')}
                  className="hidden sm:inline-flex text-sm font-medium text-slate-600 hover:text-brand transition-colors"
                >
                  Publier une annonce
                </button>
              )}

              {isAuthenticated && (
                <button
                  onClick={() => navigate('/messages')}
                  className="relative flex items-center justify-center h-9 w-9 rounded-full hover:bg-slate-100 transition-colors"
                  title="Messagerie"
                  data-testid="nav-messages-btn"
                >
                  <MessageSquare className="h-5 w-5 text-slate-600" />
                  {unread > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 bg-brand text-white text-[10px] rounded-full min-w-[16px] h-4 px-1 flex items-center justify-center" data-testid="header-unread-badge">
                      {unread > 9 ? '9+' : unread}
                    </span>
                  )}
                </button>
              )}

              {isAuthenticated ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" className="flex items-center gap-1.5 rounded-full hover:bg-slate-100" data-testid="account-menu-btn">
                      <span className="flex items-center justify-center h-7 w-7 rounded-full bg-brand/10 text-brand">
                        <User className="h-4 w-4" />
                      </span>
                      <span className="hidden sm:inline text-sm font-medium">{user?.first_name || 'Mon compte'}</span>
                      <ChevronDown className="h-4 w-4 text-slate-400" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56 rounded-xl">
                    <DropdownMenuItem onClick={handleProfileClick} className="cursor-pointer" data-testid="menu-profile">
                      <User className="h-4 w-4 mr-2" />Mon profil
                    </DropdownMenuItem>
                    {user?.user_type === 'candidate' && (
                      <>
                        <DropdownMenuItem onClick={() => navigate('/recommendations')} className="cursor-pointer" data-testid="menu-recommendations">
                          <Sparkles className="h-4 w-4 mr-2" />Recommandations IA
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/messages')} className="cursor-pointer" data-testid="menu-messages">
                          <MessageSquare className="h-4 w-4 mr-2" />Messagerie
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/my-applications')} className="cursor-pointer" data-testid="menu-applications">
                          <FileText className="h-4 w-4 mr-2" />Mes candidatures
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/my-cv')} className="cursor-pointer" data-testid="menu-cv">
                          <FileText className="h-4 w-4 mr-2" />Mes CV
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/my-cover-letters')} className="cursor-pointer" data-testid="menu-cover-letters">
                          <Mail className="h-4 w-4 mr-2" />Mes lettres de motivation
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/my-alerts')} className="cursor-pointer" data-testid="menu-alerts">
                          <Bell className="h-4 w-4 mr-2" />Mes alertes
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/saved-jobs')} className="cursor-pointer" data-testid="menu-saved">
                          <Heart className="h-4 w-4 mr-2" />Emplois sauvegardés
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/saved-searches')} className="cursor-pointer" data-testid="menu-saved-searches">
                          <History className="h-4 w-4 mr-2" />Recherches sauvegardées
                        </DropdownMenuItem>
                      </>
                    )}
                    {isEmployer && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => navigate('/recruiter-analytics')} className="cursor-pointer" data-testid="menu-analytics">
                          <BarChart3 className="h-4 w-4 mr-2" />Statistiques
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/messages')} className="cursor-pointer" data-testid="menu-employer-messages">
                          <MessageSquare className="h-4 w-4 mr-2" />Messagerie
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/my-jobs')} className="cursor-pointer" data-testid="menu-my-jobs">
                          <Briefcase className="h-4 w-4 mr-2" />Mes offres
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate('/post-job')} className="cursor-pointer" data-testid="menu-post-job">
                          <Plus className="h-4 w-4 mr-2" />Publier une offre
                        </DropdownMenuItem>
                      </>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={logout} className="cursor-pointer text-rose-600" data-testid="menu-logout">
                      <LogOut className="h-4 w-4 mr-2" />Se déconnecter
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <Button
                  onClick={() => setIsAuthOpen(true)}
                  className="rounded-full bg-brand hover:bg-brand-hover text-white px-5 transition-transform active:scale-95"
                  data-testid="login-btn"
                >
                  Se connecter
                </Button>
              )}

              <Button variant="ghost" className="md:hidden rounded-full" onClick={() => setIsMenuOpen(!isMenuOpen)} data-testid="mobile-menu-btn">
                <Menu className="h-5 w-5" />
              </Button>
            </div>
          </div>

          {isMenuOpen && (
            <div className="md:hidden py-4 border-t border-slate-200">
              <nav className="flex flex-col space-y-1">
                {NAV_LINKS.map((l) => (
                  <button key={l.label} onClick={() => { handleNav(l); setIsMenuOpen(false); }}
                    className="text-slate-700 hover:text-brand py-2 transition-colors text-left">
                    {l.label}
                  </button>
                ))}
                {isEmployer && (
                  <button onClick={() => navigate('/post-job')} className="text-slate-700 hover:text-brand py-2 transition-colors text-left">
                    Publier une annonce
                  </button>
                )}
              </nav>
            </div>
          )}
        </div>
      </header>

      <AuthModal isOpen={isAuthOpen} onClose={() => setIsAuthOpen(false)} />
    </>
  );
};

export default Header;
