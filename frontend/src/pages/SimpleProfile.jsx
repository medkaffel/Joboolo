import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import Header from '../components/Header';
import Footer from '../components/Footer';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { User, Briefcase } from 'lucide-react';

const SimpleProfile = () => {
  const { user, isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">
            Accès refusé
          </h1>
          <p className="text-gray-600">
            Vous devez être connecté pour accéder à cette page.
          </p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Mon Profil</h1>
          <p className="text-gray-600">Gérez vos informations personnelles</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          
          {/* Profile Information */}
          <div className="lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center space-x-2">
                  <User className="h-5 w-5" />
                  <span>Informations personnelles</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Prénom
                    </label>
                    <p className="text-gray-900">{user?.first_name || 'Non renseigné'}</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Nom
                    </label>
                    <p className="text-gray-900">{user?.last_name || 'Non renseigné'}</p>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Email
                  </label>
                  <p className="text-gray-900">{user?.email}</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Type de compte
                  </label>
                  <p className="text-gray-900 capitalize">{user?.user_type || 'Candidat'}</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Téléphone
                  </label>
                  <p className="text-gray-900">{user?.phone || 'Non renseigné'}</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Localisation
                  </label>
                  <p className="text-gray-900">{user?.location || 'Non renseignée'}</p>
                </div>

                <div className="pt-4">
                  <Button>
                    Modifier mes informations
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center space-x-2">
                  <Briefcase className="h-5 w-5" />
                  <span>Mes statistiques</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <span className="text-gray-600">Candidatures envoyées</span>
                    <span className="font-medium">0</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-600">Emplois sauvegardés</span>
                    <span className="font-medium">0</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-600">Profil complété</span>
                    <span className="font-medium">65%</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Actions rapides</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button className="w-full justify-start" variant="outline">
                  <Briefcase className="h-4 w-4 mr-2" />
                  Voir mes candidatures
                </Button>
                <Button className="w-full justify-start" variant="outline">
                  ❤️ Emplois sauvegardés
                </Button>
                <Button className="w-full justify-start" variant="outline" onClick={() => window.location.href = '/'}>
                  🔍 Chercher un emploi
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Welcome Message */}
        <div className="mt-8">
          <Card>
            <CardContent className="pt-6">
              <div className="text-center py-8">
                <h3 className="text-lg font-medium text-gray-900 mb-2">
                  Bienvenue sur Joboolo, {user?.first_name} ! 👋
                </h3>
                <p className="text-gray-600 mb-4">
                  Votre profil est en cours de configuration. Complétez vos informations pour augmenter vos chances de décrocher l'emploi de vos rêves !
                </p>
                <Button onClick={() => window.location.href = '/'}>
                  Découvrir les offres d'emploi
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Footer />
    </div>
  );
};

export default SimpleProfile;