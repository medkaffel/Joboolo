// Nettoie le titre d'un CV pour en extraire des mots-clés de recherche d'emploi.
// Retire "mon cv", "cv de", "cv pour", "cv_", "cv:", "CV" etc.
export const cleanCvTitle = (title) => {
  let t = title || '';
  t = t.replace(/mon\s+cv/gi, ' ');
  t = t.replace(/cv\s*(de|pour|d['’e]|:)\s*/gi, ' ');
  t = t.replace(/cv[_\s\-]+/gi, ' ');
  t = t.replace(/\bcv\b/gi, ' ');
  t = t.replace(/\.(pdf|docx?|doc)$/i, ' ');
  t = t.replace(/[_\-]+/g, ' ');
  t = t.replace(/\s+/g, ' ').trim();
  return t;
};

// Construit le lien vers la recherche d'emploi (Home lit ?q=)
export const relevantJobsHref = (title) => {
  const q = cleanCvTitle(title);
  return q ? `/?q=${encodeURIComponent(q)}` : '/';
};
