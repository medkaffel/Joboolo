import React, { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Separator } from './ui/separator';
import { useAuth } from '../contexts/AuthContext';
import { authService, friendlyAuthError } from '../services/authService';
import { useToast } from '../hooks/use-toast';

const AuthModal = ({ isOpen, onClose }) => {
  const { login, register } = useAuth();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [loginError, setLoginError] = useState('');

  const [loginData, setLoginData] = useState({ email: '', password: '', expected_user_type: 'candidate' });
  const [registerData, setRegisterData] = useState({
    email: '',
    password: '',
    confirmPassword: '',
    first_name: '',
    last_name: '',
    company_name: '',
    user_type: 'candidate'
  });

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setLoginError('');

    const result = await login(loginData);

    if (result.success) {
      toast({
        title: "Connexion réussie",
        description: "Vous êtes maintenant connecté !",
      });
      onClose();
    } else {
      setLoginError(friendlyAuthError(result.error));
    }

    setLoading(false);
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setLoading(true);

    if (registerData.password !== registerData.confirmPassword) {
      toast({
        title: "Erreur",
        description: "Les mots de passe ne correspondent pas",
        variant: "destructive",
      });
      setLoading(false);
      return;
    }

    // Partner sign-up: pending admin validation, no auto-login
    if (registerData.user_type === 'partner') {
      if (!registerData.company_name.trim()) {
        toast({ title: 'Erreur', description: "Le nom de la société est requis", variant: 'destructive' });
        setLoading(false);
        return;
      }
      try {
        const res = await authService.registerPartner({
          email: registerData.email,
          password: registerData.password,
          first_name: registerData.first_name,
          last_name: registerData.last_name,
          company_name: registerData.company_name,
        });
        toast({
          title: 'Demande envoyée',
          description: res.message || 'Votre compte partenaire sera activé après validation.',
        });
        onClose();
      } catch (err) {
        toast({ title: "Erreur d'inscription", description: err.message, variant: 'destructive' });
      } finally {
        setLoading(false);
      }
      return;
    }

    const { confirmPassword, company_name, ...userData } = registerData;
    const result = await register(userData);
    
    if (result.success) {
      toast({
        title: "Inscription réussie",
        description: "Votre compte a été créé avec succès !",
      });
      onClose();
    } else {
      toast({
        title: "Erreur d'inscription",
        description: result.error,
        variant: "destructive",
      });
    }
    
    setLoading(false);
  };

  const handleGoogleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + '/';
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-center">Rejoignez Joboolo</DialogTitle>
        </DialogHeader>
        
        {/* Google OAuth */}
        <div className="space-y-3 mb-6">
          <Button
            variant="outline"
            className="w-full h-12 justify-center gap-3"
            onClick={handleGoogleLogin}
            data-testid="google-login-btn"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0012 23z"/>
              <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 01-.34-2.1c0-.73.13-1.44.34-2.1V7.06H2.18a11 11 0 000 9.88l3.66-2.84z"/>
              <path fill="#EA4335" d="M12 4.75c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 1.46 14.97.5 12 .5A11 11 0 002.18 7.06l3.66 2.84C6.71 7.3 9.14 4.75 12 4.75z"/>
            </svg>
            Continuer avec Google
          </Button>
        </div>

        <div className="flex items-center space-x-2 mb-6">
          <Separator className="flex-1" />
          <span className="text-sm text-gray-500">ou</span>
          <Separator className="flex-1" />
        </div>
        
        <Tabs defaultValue="login" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="login">Connexion</TabsTrigger>
            <TabsTrigger value="register">Inscription</TabsTrigger>
          </TabsList>
          
          <TabsContent value="login">
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="login-usertype">Je me connecte en tant que</Label>
                <Select
                  value={loginData.expected_user_type}
                  onValueChange={(value) => { setLoginData({...loginData, expected_user_type: value}); setLoginError(''); }}
                >
                  <SelectTrigger data-testid="login-usertype-trigger">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="candidate">👤 Candidat</SelectItem>
                    <SelectItem value="employer">🏢 Recruteur</SelectItem>
                    <SelectItem value="partner">🤝 Partenaire</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="login-email">Email</Label>
                <Input
                  id="login-email"
                  type="email"
                  value={loginData.email}
                  onChange={(e) => { setLoginData({...loginData, email: e.target.value}); setLoginError(''); }}
                  placeholder="votre.email@exemple.com"
                  required
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="login-password">Mot de passe</Label>
                <Input
                  id="login-password"
                  type="password"
                  value={loginData.password}
                  onChange={(e) => setLoginData({...loginData, password: e.target.value})}
                  required
                />
              </div>
              
              <Button type="submit" className="w-full" disabled={loading} data-testid="login-submit-btn">
                {loading ? 'Connexion...' : 'Se connecter'}
              </Button>
            </form>
          </TabsContent>
          
          <TabsContent value="register">
            <form onSubmit={handleRegister} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="register-firstname">Prénom</Label>
                  <Input
                    id="register-firstname"
                    value={registerData.first_name}
                    onChange={(e) => setRegisterData({...registerData, first_name: e.target.value})}
                    placeholder="John"
                    required
                  />
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="register-lastname">Nom</Label>
                  <Input
                    id="register-lastname"
                    value={registerData.last_name}
                    onChange={(e) => setRegisterData({...registerData, last_name: e.target.value})}
                    placeholder="Doe"
                    required
                  />
                </div>
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="register-email">Email</Label>
                <Input
                  id="register-email"
                  type="email"
                  value={registerData.email}
                  onChange={(e) => setRegisterData({...registerData, email: e.target.value})}
                  placeholder="votre.email@exemple.com"
                  required
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="register-usertype">Type de compte</Label>
                <Select
                  value={registerData.user_type}
                  onValueChange={(value) => setRegisterData({...registerData, user_type: value})}
                >
                  <SelectTrigger data-testid="register-usertype-trigger">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="candidate">👤 Candidat - Je cherche un emploi</SelectItem>
                    <SelectItem value="employer">🏢 Employeur - Je recrute</SelectItem>
                    <SelectItem value="partner">🤝 Partenaire - Jobboard / Diffusion permanente</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {registerData.user_type === 'partner' && (
                <div className="space-y-2">
                  <Label htmlFor="register-company">Nom de la société</Label>
                  <Input
                    id="register-company"
                    value={registerData.company_name}
                    onChange={(e) => setRegisterData({...registerData, company_name: e.target.value})}
                    placeholder="Ex: Ma Société Diffusion"
                    data-testid="register-company-input"
                    required
                  />
                  <p className="text-xs text-slate-500">Votre compte partenaire sera activé après validation par notre équipe.</p>
                </div>
              )}
              
              <div className="space-y-2">
                <Label htmlFor="register-password">Mot de passe</Label>
                <Input
                  id="register-password"
                  type="password"
                  value={registerData.password}
                  onChange={(e) => setRegisterData({...registerData, password: e.target.value})}
                  placeholder="Minimum 6 caractères"
                  required
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="register-confirm">Confirmer le mot de passe</Label>
                <Input
                  id="register-confirm"
                  type="password"
                  value={registerData.confirmPassword}
                  onChange={(e) => setRegisterData({...registerData, confirmPassword: e.target.value})}
                  required
                />
              </div>
              
              <Button type="submit" className="w-full" disabled={loading} data-testid="register-submit-btn">
                {loading ? 'Inscription...' : 'Créer mon compte'}
              </Button>
            </form>
          </TabsContent>
        </Tabs>

        <div className="text-center mt-4">
          <p className="text-xs text-gray-500">
            En vous inscrivant, vous acceptez nos Conditions d'utilisation et notre Politique de confidentialité.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default AuthModal;