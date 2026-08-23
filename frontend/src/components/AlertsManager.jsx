import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { alertService } from '../services/alertService';
import { useToast } from '../hooks/use-toast';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Switch } from './ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Bell, Trash2, Send, Plus } from 'lucide-react';

const frequencyLabels = {
  instant: 'Instantané',
  daily: 'Quotidien',
  weekly: 'Hebdomadaire',
  never: 'Désactivé',
};

const AlertsManager = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    alertService.getMyAlerts()
      .then(setAlerts)
      .catch((e) => toast({ title: 'Erreur', description: e.message, variant: 'destructive' }))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const changeFrequency = async (id, frequency) => {
    try {
      const updated = await alertService.updateAlert(id, { frequency });
      setAlerts((prev) => prev.map((a) => (a.id === id ? updated : a)));
      toast({ title: 'Fréquence mise à jour', description: `Alerte : ${frequencyLabels[frequency]}` });
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    }
  };

  const toggleActive = async (id, is_active) => {
    try {
      const updated = await alertService.updateAlert(id, { is_active });
      setAlerts((prev) => prev.map((a) => (a.id === id ? updated : a)));
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    }
  };

  const remove = async (id) => {
    try {
      await alertService.deleteAlert(id);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
      toast({ title: 'Alerte supprimée' });
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    }
  };

  const sendNow = async (id) => {
    try {
      const res = await alertService.sendNow(id);
      toast({ title: res.sent ? 'Email envoyé' : 'Info', description: res.message });
    } catch (e) {
      toast({ title: 'Erreur', description: e.message, variant: 'destructive' });
    }
  };

  return (
    <Card data-testid="alerts-manager">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center space-x-2"><Bell className="h-5 w-5" /><span>Mes alertes emploi</span></span>
          <Button size="sm" className="bg-brand hover:bg-brand-hover" onClick={() => navigate('/')} data-testid="alerts-create-btn">
            <Plus className="h-4 w-4 mr-1" />Nouvelle alerte
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-slate-400 text-sm">Chargement...</p>
        ) : alerts.length === 0 ? (
          <p className="text-slate-400 text-sm" data-testid="alerts-empty">
            Aucune alerte. Depuis la page d'accueil, lancez une recherche puis cliquez sur « Créer une alerte » pour être notifié par email des nouvelles offres.
          </p>
        ) : (
          <div className="space-y-4" data-testid="alerts-list">
            {alerts.map((a) => (
              <div key={a.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 border rounded-lg" data-testid={`alert-item-${a.id}`}>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900">{a.name}</span>
                    {a.is_active ? (
                      <Badge className="bg-green-100 text-green-800 text-xs">Active</Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs">En pause</Badge>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-1">
                    {[a.search, a.location, a.job_type].filter(Boolean).join(' · ') || 'Toutes les offres'}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <Select value={a.frequency} onValueChange={(v) => changeFrequency(a.id, v)}>
                    <SelectTrigger className="w-36" data-testid={`alert-frequency-${a.id}`}><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(frequencyLabels).map(([val, label]) => (
                        <SelectItem key={val} value={val}>{label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Switch checked={a.is_active} onCheckedChange={(v) => toggleActive(a.id, v)} data-testid={`alert-toggle-${a.id}`} />
                  <Button variant="ghost" size="sm" className="text-brand" onClick={() => sendNow(a.id)} data-testid={`alert-send-${a.id}`} title="Recevoir maintenant">
                    <Send className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="sm" className="text-red-600" onClick={() => remove(a.id)} data-testid={`alert-delete-${a.id}`}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default AlertsManager;
