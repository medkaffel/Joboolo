export const mockJobs = [
  {
    id: 1,
    title: "Développeur Full Stack React/Node.js",
    company: "TechCorp France",
    location: "Paris (75)",
    salary: "45 000 - 55 000 € par an",
    type: "CDI",
    description: "Nous recherchons un développeur full stack expérimenté pour rejoindre notre équipe de développement. Vous travaillerez sur des projets innovants utilisant React, Node.js et MongoDB. Expérience requise : 3+ ans en développement web, maîtrise de JavaScript ES6+, connaissance de Git.",
    postedDate: "Il y a 2 jours",
    isNew: true,
    isUrgent: false
  },
  {
    id: 2,
    title: "Chef de Projet Marketing Digital",
    company: "DigitalBoost",
    location: "Lyon (69)",
    salary: "38 000 - 48 000 € par an",
    type: "CDI",
    description: "Rejoignez notre agence de marketing digital en pleine croissance ! Vous serez responsable de la gestion de projets clients, de la stratégie digitale et de l'animation d'équipe. Profil recherché : formation marketing/communication, 2+ ans d'expérience en digital.",
    postedDate: "Il y a 1 jour",
    isNew: true,
    isUrgent: true
  },
  {
    id: 3,
    title: "Infirmier(ère) Diplômé(e) d'État",
    company: "Hôpital Saint-Antoine",
    location: "Marseille (13)",
    salary: "32 000 - 38 000 € par an",
    type: "CDI",
    description: "L'hôpital Saint-Antoine recrute des infirmiers DE pour ses services de médecine générale. Vous assurerez les soins infirmiers auprès des patients hospitalisés. Diplôme d'État d'infirmier requis, expérience en milieu hospitalier appréciée.",
    postedDate: "Il y a 3 jours",
    isNew: false,
    isUrgent: true
  },
  {
    id: 4,
    title: "Commercial B2B - Secteur IT",
    company: "SoftSales Pro",
    location: "Toulouse (31)",
    salary: "35 000 - 50 000 € par an + commissions",
    type: "CDI",
    description: "Développez un portefeuille clients dans le secteur IT ! Vous prospecterez, négocierez et fidéliserez les entreprises. Formation commerciale souhaitée, goût pour les nouvelles technologies, permis B indispensable.",
    postedDate: "Il y a 1 jour",
    isNew: true,
    isUrgent: false
  },
  {
    id: 5,
    title: "Comptable Général",
    company: "Cabinet Expertise Plus",
    location: "Nantes (44)",
    salary: "30 000 - 40 000 € par an",
    type: "CDI",
    description: "Cabinet d'expertise comptable recherche un comptable général pour sa clientèle PME. Missions : tenue comptable, établissement des comptes annuels, relations clients. BTS/DUT comptabilité requis, maîtrise des logiciels comptables.",
    postedDate: "Il y a 4 jours",
    isNew: false,
    isUrgent: false
  },
  {
    id: 6,
    title: "Chargé(e) de Communication",
    company: "MediaCom Agency",
    location: "Bordeaux (33)",
    salary: "28 000 - 35 000 € par an",
    type: "CDI",
    description: "Agence de communication recrute un chargé de communication pour gérer les campagnes clients. Création de contenus, gestion des réseaux sociaux, relations presse. Formation communication, créativité et rigueur indispensables.",
    postedDate: "Il y a 5 jours",
    isNew: false,
    isUrgent: false
  },
  {
    id: 7,
    title: "Data Analyst",
    company: "DataInsights",
    location: "Paris (75)",
    salary: "40 000 - 50 000 € par an",
    type: "CDI",
    description: "Analysez et valorisez les données de nos clients ! Création de tableaux de bord, analyses statistiques, recommandations business. Maîtrise de SQL, Python/R, outils de visualisation (Tableau, Power BI). Formation analytique requise.",
    postedDate: "Il y a 2 jours",
    isNew: true,
    isUrgent: false
  },
  {
    id: 8,
    title: "Professeur des Écoles",
    company: "Éducation Nationale",
    location: "Nice (06)",
    salary: "25 000 - 30 000 € par an",
    type: "Titulaire",
    description: "Poste de professeur des écoles en élémentaire. Enseignement polyvalent du CP au CM2, suivi pédagogique des élèves, collaboration avec l'équipe éducative. Concours CRPE requis, expérience avec les enfants appréciée.",
    postedDate: "Il y a 1 semaine",
    isNew: false,
    isUrgent: true
  }
];

export const getJobsBySearch = (jobQuery, locationQuery) => {
  let filteredJobs = mockJobs;
  
  if (jobQuery) {
    filteredJobs = filteredJobs.filter(job => 
      job.title.toLowerCase().includes(jobQuery.toLowerCase()) ||
      job.description.toLowerCase().includes(jobQuery.toLowerCase()) ||
      job.company.toLowerCase().includes(jobQuery.toLowerCase())
    );
  }
  
  if (locationQuery) {
    filteredJobs = filteredJobs.filter(job => 
      job.location.toLowerCase().includes(locationQuery.toLowerCase())
    );
  }
  
  return filteredJobs;
};