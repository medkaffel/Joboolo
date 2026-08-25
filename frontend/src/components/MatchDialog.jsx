import React from 'react';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from './ui/dialog';
import { Sparkles, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';

const scoreColor = (score) => {
  if (score >= 80) return { ring: '#16a34a', text: 'text-green-600', bg: 'bg-green-50' };
  if (score >= 60) return { ring: '#0055FF', text: 'text-brand', bg: 'bg-brand-50' };
  if (score >= 40) return { ring: '#f59e0b', text: 'text-amber-600', bg: 'bg-amber-50' };
  return { ring: '#dc2626', text: 'text-red-600', bg: 'bg-red-50' };
};

export const ScoreRing = ({ score, size = 72 }) => {
  const c = scoreColor(score);
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.max(0, Math.min(100, score)) / 100) * circ;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} data-testid="score-ring">
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#e5e7eb" strokeWidth="8" fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={c.ring} strokeWidth="8" fill="none"
          strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.22,1,0.36,1)' }} />
      </svg>
      <span className={`absolute inset-0 flex items-center justify-center font-bold ${c.text}`}
        style={{ fontSize: size / 3.4 }}>
        {score}%
      </span>
    </div>
  );
};

const MatchDialog = ({ open, onOpenChange, loading, result, title = 'Analyse de compatibilité (IA)' }) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="match-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-brand" />{title}
          </DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="py-12 flex flex-col items-center justify-center text-slate-500" data-testid="match-loading">
            <Loader2 className="h-8 w-8 animate-spin text-brand mb-3" />
            <p>Analyse du profil en cours…</p>
          </div>
        ) : result ? (
          <div className="space-y-5" data-testid="match-result">
            <div className="flex items-center gap-4">
              <ScoreRing score={result.score} />
              <div>
                <p className="font-heading text-lg font-bold text-slate-900" data-testid="match-verdict">{result.verdict}</p>
                <p className="text-sm text-slate-600 mt-1">{result.summary}</p>
              </div>
            </div>

            {result.strengths?.length > 0 && (
              <div>
                <p className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-1.5">
                  <CheckCircle2 className="h-4 w-4 text-green-600" />Points forts
                </p>
                <ul className="space-y-1.5">
                  {result.strengths.map((s, i) => (
                    <li key={`strength-${i}`} className="text-sm text-slate-600 flex items-start gap-2">
                      <span className="text-green-600 mt-0.5">•</span>{s}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {result.gaps?.length > 0 && (
              <div>
                <p className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-1.5">
                  <AlertTriangle className="h-4 w-4 text-amber-600" />À renforcer
                </p>
                <ul className="space-y-1.5">
                  {result.gaps.map((g, i) => (
                    <li key={`gap-${i}`} className="text-sm text-slate-600 flex items-start gap-2">
                      <span className="text-amber-600 mt-0.5">•</span>{g}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-xs text-slate-400 pt-2 border-t">Analyse générée par IA (Claude) — à titre indicatif.</p>
          </div>
        ) : (
          <p className="py-8 text-center text-slate-400" data-testid="match-error">Analyse indisponible pour le moment.</p>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default MatchDialog;
