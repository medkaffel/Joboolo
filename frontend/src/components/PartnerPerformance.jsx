import React, { useState, useEffect } from 'react';
import { paymentService } from '../services/paymentService';
import { Card, CardContent } from './ui/card';
import { BarChart3, MousePointerClick, Euro, Percent, TrendingUp } from 'lucide-react';

const Stat = ({ icon: Icon, label, value, accent }) => (
  <div className="flex items-center gap-3">
    <div className={`h-10 w-10 rounded-xl flex items-center justify-center ${accent}`}><Icon className="h-5 w-5" /></div>
    <div>
      <div className="font-heading text-xl font-bold text-slate-900">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  </div>
);

const PartnerPerformance = () => {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(14);

  useEffect(() => { paymentService.partnerPerformance(days).then(setData).catch(() => {}); }, [days]);

  if (!data) return null;
  const maxClicks = Math.max(1, ...data.daily.map((d) => d.clicks));
  const t = data.totals;

  return (
    <div data-testid="partner-performance">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-heading text-xl font-semibold text-slate-900 flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-brand" /> Performance de mes campagnes
        </h2>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value))}
          className="text-sm border border-slate-200 rounded-full px-4 py-2 bg-white focus:outline-none text-slate-600"
          data-testid="performance-period"
        >
          <option value={7}>7 derniers jours</option>
          <option value={14}>14 derniers jours</option>
          <option value={30}>30 derniers jours</option>
        </select>
      </div>

      <Card className="rounded-2xl mb-8">
        <CardContent className="p-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <Stat icon={MousePointerClick} label="Clics" value={t.clicks} accent="bg-brand/10 text-brand" />
            <Stat icon={Euro} label="Coût total" value={`${t.cost.toFixed(2)} €`} accent="bg-amber-100 text-amber-700" />
            <Stat icon={TrendingUp} label="CPC moyen" value={`${t.avg_cpc.toFixed(2)} €`} accent="bg-emerald-100 text-emerald-700" />
            <Stat icon={Percent} label="Taux de clic (CTR)" value={`${t.ctr.toFixed(1)} %`} accent="bg-violet-100 text-violet-700" />
          </div>

          {/* CSS bar chart — clicks per day */}
          <div className="border-t border-slate-100 pt-5">
            <p className="text-xs text-slate-400 mb-3">Clics par jour</p>
            <div className="flex items-end gap-1.5 h-40" data-testid="performance-chart">
              {data.daily.map((d, i) => (
                <div key={i} className="flex-1 flex flex-col items-center justify-end group" title={`${d.date} — ${d.clicks} clic(s) · ${d.cost.toFixed(2)} €`}>
                  <span className="text-[10px] text-slate-400 mb-1 opacity-0 group-hover:opacity-100 transition-opacity">{d.clicks}</span>
                  <div
                    className="w-full rounded-t-md bg-brand/80 hover:bg-brand transition-all"
                    style={{ height: `${Math.max(4, (d.clicks / maxClicks) * 130)}px` }}
                  />
                  <span className="text-[9px] text-slate-400 mt-1 rotate-0 truncate w-full text-center">{d.date.slice(5)}</span>
                </div>
              ))}
            </div>
          </div>

          {data.top_jobs.length > 0 && (
            <div className="border-t border-slate-100 pt-5 mt-5">
              <p className="text-xs text-slate-400 mb-3">Offres les plus performantes</p>
              <ul className="space-y-2">
                {data.top_jobs.map((j, i) => (
                  <li key={i} className="flex items-center justify-between text-sm" data-testid={`top-job-${i}`}>
                    <span className="text-slate-700 truncate flex-1">{j.title}</span>
                    <span className="text-slate-500 shrink-0 ml-3">{j.clicks} clic(s) · {j.cost.toFixed(2)} €</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default PartnerPerformance;
