import React, { useState, useEffect } from 'react';
import { Separator } from './ui/separator';
import { ExternalLink } from 'lucide-react';
import api from '../services/api';

const DEFAULT_INTERNATIONAL = [
  { code: 'es', label: 'Empleo en España', url: 'https://es.joboolo.com' },
  { code: 'de', label: 'Stellenangebote in Deutschland', url: 'https://de.joboolo.com' },
  { code: 'it', label: 'Lavoro in Italia', url: 'https://it.joboolo.com' },
  { code: 'pt', label: 'Emprego em Portugal', url: 'https://pt.joboolo.com' },
  { code: 'ie', label: 'Jobs in Ireland', url: 'https://ie.joboolo.com' },
  { code: 'be', label: 'Emplois en Belgique', url: 'https://be.joboolo.com' },
  { code: 'gb', label: 'Jobs in the United Kingdom', url: 'https://gb.joboolo.com' },
  { code: 'ch', label: 'Stellenangebote in der Schweiz', url: 'https://ch.joboolo.com' },
  { code: 'ru', label: 'Работа в России', url: 'https://ru.joboolo.com' },
  { code: 'br', label: 'Emprego no Brasil', url: 'https://br.joboolo.com' },
  { code: 'au', label: 'Jobs in Australia', url: 'https://au.joboolo.com' },
  { code: 'mx', label: 'Empleo en México', url: 'https://mx.joboolo.com' },
  { code: 'at', label: 'Jobs in Österreich', url: 'https://at.joboolo.com' },
];

const flagUrl = (code) => `https://flagcdn.com/w40/${(code || '').toLowerCase()}.png`;

const Footer = () => {
  const [countries, setCountries] = useState(DEFAULT_INTERNATIONAL);

  useEffect(() => {
    api.get('/footer-countries')
      .then((res) => { if (Array.isArray(res.data) && res.data.length) setCountries(res.data); })
      .catch(() => {});
  }, []);

  const footerSections = [
    {
      title: 'Recherche emploi',
      links: [
        'Emploi par ville',
        'Emploi par région',
        'Emploi par secteur',
        'Toutes les offres',
        'Recherche avancée'
      ]
    },
    {
      title: 'Ressources',
      links: [
        'Guide CV',
        'Guide entretien',
        'Conseils carrière',
        'Formation',
        'Centre d\'aide'
      ]
    },
    {
      title: 'Joboolo',
      links: [
        'À propos',
        'Presse',
        'Relations investisseurs',
        'Carrières chez Joboolo',
        'Avis sur Joboolo'
      ]
    },
    {
      title: 'Employeurs',
      links: [
        'Publier une offre',
        'Gérer les candidatures',
        'Solutions recrutement',
        'Tarifs',
        'Support employeurs'
      ]
    }
  ];

  return (
    <footer className="bg-slate-900 text-slate-400">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-14">
        {/* Brand row */}
        <div className="mb-10">
          <span className="font-heading text-2xl font-extrabold text-white">
            Job<span className="text-brand">oolo</span>
          </span>
          <p className="mt-3 text-sm text-slate-400 max-w-md">
            La plateforme d'emploi qui connecte les meilleurs talents aux entreprises qui recrutent en France.
          </p>
        </div>

        {/* Main Footer Content */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-8">
          {footerSections.map((section, index) => (
            <div key={index}>
              <h3 className="text-white font-heading font-semibold mb-4 text-sm uppercase tracking-widest">
                {section.title}
              </h3>
              <ul className="space-y-2.5">
                {section.links.map((link, linkIndex) => (
                  <li key={linkIndex}>
                    <a 
                      href="#" 
                      className="text-sm hover:text-brand transition-colors"
                    >
                      {link}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <Separator className="bg-slate-800 mb-8" />

        {/* International versions */}
        <div className="mb-8" data-testid="footer-international">
          <h3 className="text-white font-heading font-semibold mb-4 text-sm uppercase tracking-widest">
            Joboolo est également présent dans d'autres pays
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5">
            {countries.map((c) => {
              const isLink = c.url && c.url !== '#';
              return (
                <a
                  key={c.id || c.code}
                  href={c.url || '#'}
                  target={isLink ? '_blank' : undefined}
                  rel={isLink ? 'noopener noreferrer' : undefined}
                  className="group flex items-center gap-2 text-sm text-slate-400 hover:text-brand transition-colors"
                  data-testid={`footer-country-${c.code}`}
                >
                  <img
                    src={flagUrl(c.code)}
                    alt={c.code}
                    loading="lazy"
                    className="h-3.5 w-5 object-cover rounded-[2px] shrink-0 ring-1 ring-white/10"
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                  />
                  <span className="truncate">{c.label}</span>
                  {isLink && (
                    <ExternalLink className="h-3 w-3 shrink-0 opacity-0 group-hover:opacity-70 transition-opacity" />
                  )}
                </a>
              );
            })}
          </div>
        </div>

        <Separator className="bg-slate-800 mb-8" />

        {/* Bottom Footer */}
        <div className="flex flex-col md:flex-row justify-between items-center gap-4">
          <div className="flex items-center space-x-6">
            <span className="text-sm">© 2026 Joboolo</span>
            <a href="#" className="text-sm hover:text-brand transition-colors">Cookies</a>
            <a href="#" className="text-sm hover:text-brand transition-colors">Confidentialité</a>
            <a href="#" className="text-sm hover:text-brand transition-colors">Conditions</a>
          </div>
          
          <div className="flex items-center space-x-4">
            <span className="text-sm">Suivez-nous :</span>
            <div className="flex space-x-3">
              <a href="#" className="text-slate-400 hover:text-brand transition-colors">Facebook</a>
              <a href="#" className="text-slate-400 hover:text-brand transition-colors">Twitter</a>
              <a href="#" className="text-slate-400 hover:text-brand transition-colors">LinkedIn</a>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;