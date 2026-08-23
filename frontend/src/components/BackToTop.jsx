import React, { useState, useEffect } from 'react';
import { ArrowUp } from 'lucide-react';

const BackToTop = () => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 400);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  if (!visible) return null;

  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      aria-label="Remonter en haut"
      data-testid="back-to-top-btn"
      className="fixed bottom-6 right-6 z-50 h-12 w-12 rounded-full bg-brand text-white shadow-lg flex items-center justify-center hover:bg-brand-hover transition-all hover:-translate-y-0.5 animate-fade-up"
    >
      <ArrowUp className="h-5 w-5" />
    </button>
  );
};

export default BackToTop;
