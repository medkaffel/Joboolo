// Service d'authentification OAuth
export const oauthService = {
  // URLs de redirection OAuth (à configurer avec vos clés API)
  providers: {
    google: {
      name: 'Google',
      icon: '🔴',
      clientId: process.env.REACT_APP_GOOGLE_CLIENT_ID,
      redirectUri: `${window.location.origin}/auth/callback/google`,
      scope: 'openid email profile',
      authUrl: 'https://accounts.google.com/o/oauth2/v2/auth'
    },
    facebook: {
      name: 'Facebook',
      icon: '🔵',
      clientId: process.env.REACT_APP_FACEBOOK_APP_ID,
      redirectUri: `${window.location.origin}/auth/callback/facebook`,
      scope: 'email',
      authUrl: 'https://www.facebook.com/v18.0/dialog/oauth'
    },
    linkedin: {
      name: 'LinkedIn',
      icon: '🔷',
      clientId: process.env.REACT_APP_LINKEDIN_CLIENT_ID,
      redirectUri: `${window.location.origin}/auth/callback/linkedin`,
      scope: 'openid profile email',
      authUrl: 'https://www.linkedin.com/oauth/v2/authorization'
    },
    twitter: {
      name: 'X (Twitter)',
      icon: '⚫',
      clientId: process.env.REACT_APP_TWITTER_CLIENT_ID,
      redirectUri: `${window.location.origin}/auth/callback/twitter`,
      scope: 'tweet.read users.read',
      authUrl: 'https://twitter.com/i/oauth2/authorize'
    }
  },

  // Générer l'URL d'authentification OAuth
  generateAuthUrl(provider) {
    const config = this.providers[provider];
    if (!config || !config.clientId) {
      throw new Error(`Provider ${provider} not configured`);
    }

    const params = new URLSearchParams({
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      scope: config.scope,
      response_type: 'code',
      state: this.generateState(provider)
    });

    // Paramètres spécifiques par provider
    if (provider === 'google') {
      params.append('access_type', 'offline');
      params.append('prompt', 'consent');
    } else if (provider === 'linkedin') {
      params.append('response_type', 'code');
    } else if (provider === 'twitter') {
      params.append('code_challenge', this.generateCodeChallenge());
      params.append('code_challenge_method', 'S256');
    }

    return `${config.authUrl}?${params.toString()}`;
  },

  // Générer un state sécurisé pour prévenir les attaques CSRF
  generateState(provider) {
    const state = {
      provider,
      nonce: Math.random().toString(36).substring(2, 15),
      timestamp: Date.now()
    };
    const encodedState = btoa(JSON.stringify(state));
    localStorage.setItem('oauth_state', encodedState);
    return encodedState;
  },

  // Générer code challenge pour Twitter (PKCE)
  generateCodeChallenge() {
    // Simplified version - in production use proper crypto
    const codeVerifier = Math.random().toString(36).substring(2, 128);
    localStorage.setItem('code_verifier', codeVerifier);
    // For simplicity, using plain text (in production, use SHA256 hash)
    return codeVerifier;
  },

  // Vérifier le state de retour
  validateState(returnedState) {
    const storedState = localStorage.getItem('oauth_state');
    if (!storedState || storedState !== returnedState) {
      throw new Error('Invalid OAuth state');
    }
    
    const state = JSON.parse(atob(returnedState));
    // Vérifier que le state n'est pas trop ancien (5 minutes max)
    if (Date.now() - state.timestamp > 5 * 60 * 1000) {
      throw new Error('OAuth state expired');
    }
    
    return state;
  },

  // Initier l'authentification OAuth
  async authenticateWith(provider) {
    try {
      const authUrl = this.generateAuthUrl(provider);
      
      // Ouvrir la popup OAuth
      const popup = window.open(
        authUrl,
        `oauth_${provider}`,
        'width=600,height=600,scrollbars=yes,resizable=yes'
      );

      return new Promise((resolve, reject) => {
        // Surveiller la popup
        const checkClosed = setInterval(() => {
          if (popup.closed) {
            clearInterval(checkClosed);
            reject(new Error('Authentication cancelled'));
          }
        }, 1000);

        // Écouter les messages de la popup
        const messageHandler = (event) => {
          if (event.origin !== window.location.origin) return;
          
          if (event.data.type === 'OAUTH_SUCCESS') {
            clearInterval(checkClosed);
            window.removeEventListener('message', messageHandler);
            popup.close();
            resolve(event.data);
          } else if (event.data.type === 'OAUTH_ERROR') {
            clearInterval(checkClosed);
            window.removeEventListener('message', messageHandler);
            popup.close();
            reject(new Error(event.data.error));
          }
        };

        window.addEventListener('message', messageHandler);
      });
    } catch (error) {
      throw new Error(`OAuth authentication failed: ${error.message}`);
    }
  },

  // Simuler l'authentification OAuth (pour la démo)
  async simulateOAuthLogin(provider) {
    // Simuler un délai de connexion
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Données simulées de l'utilisateur OAuth
    const mockUsers = {
      google: {
        email: 'user@gmail.com',
        first_name: 'John',
        last_name: 'Doe',
        provider: 'google',
        provider_id: 'google_123456789'
      },
      facebook: {
        email: 'user@facebook.com',
        first_name: 'Jane',
        last_name: 'Smith',
        provider: 'facebook',
        provider_id: 'facebook_987654321'
      },
      linkedin: {
        email: 'user@linkedin.com',
        first_name: 'Mike',
        last_name: 'Johnson',
        provider: 'linkedin',
        provider_id: 'linkedin_456789123'
      },
      twitter: {
        email: 'user@twitter.com',
        first_name: 'Sarah',
        last_name: 'Wilson',
        provider: 'twitter',
        provider_id: 'twitter_321654987'
      }
    };

    return mockUsers[provider] || mockUsers.google;
  }
};