import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { messageService } from '../services/messageService';
import { useToast } from '../hooks/use-toast';
import Header from '../components/Header';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { MessageSquare, Send, User as UserIcon, Loader2 } from 'lucide-react';

const fmtTime = (iso) => {
  try { return new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  catch { return ''; }
};

const Messages = () => {
  const { isAuthenticated, user } = useAuth();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTo = searchParams.get('to');

  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(initialTo || null);
  const [thread, setThread] = useState(null);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const scrollRef = useRef(null);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await messageService.getConversations());
    } catch (error) {
      console.error('Échec du chargement des conversations:', error);
    }
  }, []);

  const loadThread = useCallback(async (otherId) => {
    if (!otherId) return;
    try {
      const data = await messageService.getThread(otherId);
      setThread(data);
    } catch (e) {
      toast({ title: 'Erreur', description: e.response?.data?.detail || e.message, variant: 'destructive' });
    }
  }, [toast]);

  // initial + polling for conversation list
  useEffect(() => {
    if (!isAuthenticated) return;
    loadConversations();
    const t = setInterval(loadConversations, 6000);
    return () => clearInterval(t);
  }, [isAuthenticated, loadConversations]);

  // when active conversation changes -> load thread, then poll
  useEffect(() => {
    if (!activeId) { setThread(null); return; }
    setLoadingThread(true);
    loadThread(activeId).finally(() => setLoadingThread(false));
    const t = setInterval(() => loadThread(activeId), 4000);
    return () => clearInterval(t);
  }, [activeId, loadThread]);

  // auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [thread?.messages?.length, activeId]);

  const openConversation = (otherId) => {
    setActiveId(otherId);
    setSearchParams({ to: otherId });
  };

  const handleSend = async (e) => {
    e?.preventDefault();
    const body = text.trim();
    if (!body || !activeId) return;
    setSending(true);
    try {
      await messageService.send({ recipient_id: activeId, text: body });
      setText('');
      await loadThread(activeId);
      loadConversations();
    } catch (err) {
      toast({ title: 'Erreur', description: err.response?.data?.detail || err.message, variant: 'destructive' });
    } finally {
      setSending(false);
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Header />
        <div className="max-w-4xl mx-auto px-4 py-16 text-center" data-testid="messages-access-denied">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mb-4">Connectez-vous</h1>
          <p className="text-slate-500">Accédez à votre messagerie une fois connecté.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="messages-page">
        <h1 className="font-heading text-3xl font-bold tracking-tight text-slate-900 mb-6 flex items-center gap-2">
          <MessageSquare className="h-7 w-7 text-brand" />Messagerie
        </h1>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 h-[70vh]">
          {/* Conversation list */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-y-auto" data-testid="conversation-list">
            {conversations.length === 0 ? (
              <div className="p-6 text-center text-slate-400 text-sm">Aucune conversation pour l'instant.</div>
            ) : conversations.map((c) => (
              <button key={c.other_id} onClick={() => openConversation(c.other_id)}
                className={`w-full text-left p-4 border-b border-slate-100 hover:bg-slate-50 transition-colors flex items-center gap-3 ${activeId === c.other_id ? 'bg-brand-50' : ''}`}
                data-testid={`conversation-${c.other_id}`}>
                <span className="flex items-center justify-center h-10 w-10 rounded-full bg-brand/10 text-brand shrink-0">
                  <UserIcon className="h-5 w-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-900 truncate">{c.name}</span>
                    {c.unread > 0 && (
                      <span className="bg-brand text-white text-xs rounded-full px-2 py-0.5" data-testid={`unread-${c.other_id}`}>{c.unread}</span>
                    )}
                  </span>
                  <span className="block text-sm text-slate-500 truncate">
                    {c.last_from_me ? 'Vous : ' : ''}{c.last_message}
                  </span>
                </span>
              </button>
            ))}
          </div>

          {/* Thread */}
          <div className="md:col-span-2 bg-white rounded-xl border border-slate-200 flex flex-col" data-testid="thread-panel">
            {!activeId ? (
              <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
                <MessageSquare className="h-12 w-12 mb-3 opacity-50" />
                <p>Sélectionnez une conversation</p>
              </div>
            ) : (
              <>
                <div className="p-4 border-b border-slate-200 flex items-center gap-3">
                  <span className="flex items-center justify-center h-9 w-9 rounded-full bg-brand/10 text-brand">
                    <UserIcon className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="font-semibold text-slate-900" data-testid="thread-name">{thread?.other?.name || '...'}</p>
                    <p className="text-xs text-slate-400 capitalize">{thread?.other?.user_type === 'candidate' ? 'Candidat' : 'Recruteur'}</p>
                  </div>
                </div>

                <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3" data-testid="thread-messages">
                  {loadingThread && !thread ? (
                    <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-brand" /></div>
                  ) : (thread?.messages || []).length === 0 ? (
                    <p className="text-center text-slate-400 text-sm py-8">Démarrez la conversation ci-dessous.</p>
                  ) : (thread?.messages || []).map((m) => (
                    <div key={m.id} className={`flex ${m.from_me ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[75%] rounded-2xl px-4 py-2 ${m.from_me ? 'bg-brand text-white rounded-br-sm' : 'bg-slate-100 text-slate-800 rounded-bl-sm'}`}
                        data-testid={`message-${m.id}`}>
                        <p className="text-sm whitespace-pre-line break-words">{m.text}</p>
                        <p className={`text-[10px] mt-1 ${m.from_me ? 'text-white/70' : 'text-slate-400'}`}>{fmtTime(m.created_at)}</p>
                      </div>
                    </div>
                  ))}
                </div>

                <form onSubmit={handleSend} className="p-3 border-t border-slate-200 flex items-center gap-2">
                  <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Écrivez un message…"
                    className="flex-1" data-testid="message-input" />
                  <Button type="submit" disabled={sending || !text.trim()} className="bg-brand hover:bg-brand-hover" data-testid="message-send-btn">
                    {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </Button>
                </form>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Messages;
