import React from 'react';
import { Button } from '../ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Plus, Eye } from 'lucide-react';

/**
 * Shared header for every admin list.
 * Shows: "N enregistrement(s) — <label>" + a "Nouveau" primary button.
 * Extra content (search fields, filters) is rendered as children between the count and the CTA.
 */
export const AdminListHeader = ({ count, label, onCreate, createLabel = 'Nouveau', createTestId, children }) => (
  <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
    <div className="flex items-center gap-3 flex-wrap">
      <span className="text-sm font-semibold text-slate-700" data-testid={`${createTestId}-count`}>
        {count} {label}{count > 1 && !label.endsWith('s') ? 's' : ''}
      </span>
      {children}
    </div>
    {onCreate && (
      <Button
        className="bg-brand hover:bg-brand-hover shrink-0"
        onClick={onCreate}
        data-testid={createTestId}
      >
        <Plus className="h-4 w-4 mr-1" />{createLabel}
      </Button>
    )}
  </div>
);

/** Formats a value nicely for the detail modal. */
const fmt = (v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Oui' : 'Non';
  if (v instanceof Date) return v.toLocaleString('fr-FR');
  if (Array.isArray(v)) return v.length ? v.join(', ') : '—';
  if (typeof v === 'object') return JSON.stringify(v, null, 2);
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) {
    try { return new Date(v).toLocaleString('fr-FR'); } catch { return v; }
  }
  return String(v);
};

/**
 * Generic detail dialog — flattens the record into a readable key/value grid.
 * @param fields Optional list of {key, label, render?} to control what/how to display.
 *               If not provided, every own field of `record` is shown.
 */
export const DetailDialog = ({ open, onOpenChange, title, record, fields }) => {
  if (!record) return null;
  const items = fields && fields.length > 0
    ? fields
    : Object.keys(record).map((k) => ({ key: k, label: k.replace(/_/g, ' ') }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="admin-detail-dialog">
        <DialogHeader>
          <DialogTitle className="font-heading flex items-center gap-2">
            <Eye className="h-5 w-5 text-brand" />{title || 'Détails de l\u2019enregistrement'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          {items.map(({ key, label, render }) => {
            const raw = key.split('.').reduce((o, k) => (o == null ? o : o[k]), record);
            const val = render ? render(raw, record) : fmt(raw);
            return (
              <div key={key} className="grid grid-cols-3 gap-3 py-1.5 border-b border-slate-100 last:border-0">
                <div className="text-xs uppercase tracking-wide text-slate-400 col-span-1 pt-0.5">{label}</div>
                <div className="text-sm text-slate-700 col-span-2 whitespace-pre-wrap break-words">{val}</div>
              </div>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
};

/** Clickable text cell → triggers a detail dialog. Uses button semantics for accessibility. */
export const DetailLinkCell = ({ onOpen, children, testId }) => (
  <button
    type="button"
    onClick={onOpen}
    className="text-brand hover:text-brand-hover hover:underline font-medium text-left"
    data-testid={testId}
  >
    {children}
  </button>
);
