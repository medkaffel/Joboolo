import React, { useState, useEffect } from 'react';
import { locationService } from '../services/locationService';
import { useAuth } from '../contexts/AuthContext';

const WelcomeMessage = () => {
  const { user, isAuthenticated } = useAuth();
  const [locationInfo, setLocationInfo] = useState({
    greeting: 'Bonjour',
    countryName: 'Visiteur',
    countryCode: 'FR',
    isDetected: false,
  });

  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    locationService.getLocationInfo()
      .then((info) => { if (active) setLocationInfo((prev) => ({ ...prev, ...info })); })
      .catch(() => {});
    return () => { active = false; };
  }, [isAuthenticated]);

  // Rien pour les visiteurs non connectés
  if (!isAuthenticated) return null;

  const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(' ').trim();

  return (
    <div className="text-center mb-8" data-testid="welcome-message">
      <div className="inline-flex items-center gap-2 rounded-full bg-white border border-slate-200 px-4 py-1.5 text-sm font-medium text-slate-700 shadow-sm">
        <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-brand font-semibold" data-testid="welcome-greeting">
          {locationInfo.greeting}{fullName ? ` ${fullName}` : ''}
        </span>
        {locationInfo.isDetected && locationInfo.countryCode !== 'FR' && (
          <span className="text-slate-500">depuis {locationInfo.countryName} {getFlagEmoji(locationInfo.countryCode)}</span>
        )}
      </div>

      {locationInfo.countryCode !== 'FR' && locationInfo.isDetected && (
        <div className="mt-4 bg-brand/5 border border-brand/15 rounded-xl px-4 py-3 max-w-md mx-auto">
          <p className="text-sm text-brand">
            <span className="font-semibold">Info :</span> Joboolo est spécialisé dans les emplois en France.
          </p>
        </div>
      )}
    </div>
  );
};

// Fonction pour obtenir le drapeau emoji d'un pays
const getFlagEmoji = (countryCode) => {
  const flagEmojis = {
    FR: '🇫🇷', GB: '🇬🇧', US: '🇺🇸', CA: '🇨🇦', AU: '🇦🇺', NZ: '🇳🇿', IE: '🇮🇪',
    ES: '🇪🇸', MX: '🇲🇽', AR: '🇦🇷', IT: '🇮🇹', DE: '🇩🇪', AT: '🇦🇹', CH: '🇨🇭',
    PT: '🇵🇹', BR: '🇧🇷', NL: '🇳🇱', BE: '🇧🇪', PL: '🇵🇱', RU: '🇷🇺', JP: '🇯🇵',
    CN: '🇨🇳', KR: '🇰🇷', SA: '🇸🇦', TR: '🇹🇷', GR: '🇬🇷', SE: '🇸🇪', NO: '🇳🇴',
    DK: '🇩🇰', FI: '🇫🇮', CZ: '🇨🇿', HU: '🇭🇺', RO: '🇷🇴', BG: '🇧🇬', HR: '🇭🇷',
    SK: '🇸🇰', SI: '🇸🇮', EE: '🇪🇪', LV: '🇱🇻', LT: '🇱🇹', MT: '🇲🇹'
  };

  return flagEmojis[countryCode] || '🌍';
};

export default WelcomeMessage;
