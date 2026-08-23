// Service de détection de localisation et traduction
export const locationService = {
  // Traductions pour "Bonjour" dans différentes langues
  greetings: {
    // Français (par défaut)
    FR: 'Bonjour',
    // Anglais
    GB: 'Hello',
    US: 'Hello',
    CA: 'Hello', // Canada anglophone
    AU: 'Hello',
    NZ: 'Hello',
    IE: 'Hello',
    // Espagnol
    ES: 'Hola',
    MX: 'Hola',
    AR: 'Hola',
    CO: 'Hola',
    CL: 'Hola',
    PE: 'Hola',
    // Italien
    IT: 'Ciao',
    // Allemand
    DE: 'Hallo',
    AT: 'Hallo',
    CH: 'Hallo', // Suisse (allemand)
    // Portugais
    PT: 'Olá',
    BR: 'Olá',
    // Néerlandais
    NL: 'Hallo',
    BE: 'Hallo', // Belgique (néerlandais)
    // Polonais
    PL: 'Cześć',
    // Russe
    RU: 'Привет',
    // Japonais
    JP: 'こんにちは',
    // Chinois
    CN: '你好',
    // Coréen
    KR: '안녕하세요',
    // Arabe
    SA: 'مرحبا',
    AE: 'مرحبا',
    EG: 'مرحبا',
    // Turc
    TR: 'Merhaba',
    // Grec
    GR: 'Γεια σας',
    // Suédois
    SE: 'Hej',
    // Norvégien
    NO: 'Hei',
    // Danois
    DK: 'Hej',
    // Finlandais
    FI: 'Hei',
    // Tchèque
    CZ: 'Ahoj',
    // Hongrois
    HU: 'Szia',
    // Roumain
    RO: 'Salut',
    // Bulgare
    BG: 'Здравей',
    // Croate
    HR: 'Bok',
    // Slovaque
    SK: 'Ahoj',
    // Slovène
    SI: 'Živjo',
    // Estonien
    EE: 'Tere',
    // Letton
    LV: 'Sveiki',
    // Lituanien
    LT: 'Labas',
    // Maltais
    MT: 'Bonġu'
  },

  // Noms de pays traduits en français
  countryNames: {
    FR: 'France',
    GB: 'Royaume-Uni',
    US: 'États-Unis',
    CA: 'Canada',
    AU: 'Australie',
    NZ: 'Nouvelle-Zélande',
    IE: 'Irlande',
    ES: 'Espagne',
    MX: 'Mexique',
    AR: 'Argentine',
    IT: 'Italie',
    DE: 'Allemagne',
    AT: 'Autriche',
    CH: 'Suisse',
    PT: 'Portugal',
    BR: 'Brésil',
    NL: 'Pays-Bas',
    BE: 'Belgique',
    PL: 'Pologne',
    RU: 'Russie',
    JP: 'Japon',
    CN: 'Chine',
    KR: 'Corée du Sud',
    SA: 'Arabie Saoudite',
    TR: 'Turquie',
    GR: 'Grèce',
    SE: 'Suède',
    NO: 'Norvège',
    DK: 'Danemark',
    FI: 'Finlande',
    CZ: 'République Tchèque',
    HU: 'Hongrie',
    RO: 'Roumanie'
  },

  // Détecter le pays via l'API de géolocalisation IP
  async detectCountry() {
    try {
      // Essayer plusieurs services de géolocalisation IP
      const services = [
        'https://ipapi.co/country_code/',
        'https://api.country.is/',
        'https://ipinfo.io/country'
      ];

      for (const service of services) {
        try {
          const response = await fetch(service);
          if (response.ok) {
            let countryCode;
            
            if (service.includes('country.is')) {
              const data = await response.json();
              countryCode = data.country;
            } else {
              countryCode = await response.text();
            }
            
            // Nettoyer le code pays
            countryCode = countryCode.trim().toUpperCase();
            
            if (countryCode && countryCode.length === 2) {
              console.log(`Pays détecté: ${countryCode} via ${service}`);
              return countryCode;
            }
          }
        } catch (error) {
          console.warn(`Service ${service} failed:`, error);
          continue;
        }
      }
      
      // Fallback: essayer de détecter via la langue du navigateur
      const browserLang = navigator.language || navigator.languages[0];
      const langCode = browserLang.split('-')[1]?.toUpperCase();
      
      if (langCode && this.greetings[langCode]) {
        console.log(`Utilisation langue navigateur: ${langCode}`);
        return langCode;
      }
      
      // Fallback ultime
      return 'FR';
    } catch (error) {
      console.error('Erreur détection pays:', error);
      return 'FR'; // Défaut français
    }
  },

  // Obtenir le message de bienvenue pour un pays
  getGreeting(countryCode) {
    return this.greetings[countryCode] || this.greetings['FR'];
  },

  // Obtenir le nom du pays
  getCountryName(countryCode) {
    return this.countryNames[countryCode] || 'Visiteur international';
  },

  // Détecter automatiquement et retourner les informations complètes
  async getLocationInfo() {
    const countryCode = await this.detectCountry();
    return {
      countryCode,
      greeting: this.getGreeting(countryCode),
      countryName: this.getCountryName(countryCode),
      isDetected: countryCode !== 'FR' || this.isLikelyFrench()
    };
  },

  // Vérifier si l'utilisateur est probablement français
  isLikelyFrench() {
    const browserLang = navigator.language || navigator.languages[0];
    return browserLang.toLowerCase().startsWith('fr');
  }
};