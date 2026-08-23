import React from 'react';
import { BellRing, Clock, FileSearch } from 'lucide-react';

const REASONS = [
  {
    icon: BellRing,
    title: 'Ne ratez aucune offre',
    text: "Soyez alerté par email dès qu'une nouvelle offre d'emploi correspond à votre profil.",
  },
  {
    icon: Clock,
    title: 'Gagnez du temps',
    text: "Joboolo regroupe pour vous toutes les offres du marché, quel que soit le secteur ou le type de poste visé.",
  },
  {
    icon: FileSearch,
    title: 'Plus besoin de chercher',
    text: "Vous avez un CV ? Grâce à son analyse, nous trouvons pour vous les offres qui correspondent à votre profil.",
  },
];

const WhyJoboolo = () => (
  <section className="bg-white py-16" data-testid="why-joboolo-section">
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
      <h2 className="font-heading text-3xl font-bold tracking-tight text-slate-900 text-center mb-3">
        3 bonnes raisons d'utiliser <span className="text-brand">Joboolo</span>
      </h2>
      <p className="text-slate-500 text-center max-w-xl mx-auto mb-12">
        La recherche d'emploi, simplifiée et personnalisée.
      </p>
      <div className="grid md:grid-cols-3 gap-8">
        {REASONS.map((r, i) => (
          <div
            key={i}
            className="rounded-2xl border border-slate-100 p-8 hover:shadow-lg hover:-translate-y-1 transition-all bg-slate-50/50"
            data-testid={`why-reason-${i}`}
          >
            <div className="h-14 w-14 rounded-2xl bg-brand/10 text-brand flex items-center justify-center mb-5">
              <r.icon className="h-7 w-7" />
            </div>
            <h3 className="font-heading text-lg font-semibold text-slate-900 mb-2">{r.title}</h3>
            <p className="text-slate-500 text-sm leading-relaxed">{r.text}</p>
          </div>
        ))}
      </div>
    </div>
  </section>
);

export default WhyJoboolo;
