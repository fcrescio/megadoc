import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { getKnowledgeAgentRun, streamKnowledgeAgent } from '../api/client';
import {
  useCanonicalEntities,
  useGraphConsolidationSuggestions,
  useKnowledgeAssertions,
  useKnowledgeEntities,
  useKnowledgeEntityDetail,
  useKnowledgeNode,
  useKnowledgeNodes,
  useKnowledgeSearch,
  useKnowledgeAgentRuns,
  useMergeCanonicalEntity,
  useKnowledgeTopic,
  useKnowledgeTopics,
  useReviewGraphConsolidationSuggestion,
  useRunKnowledgeConsolidation,
  useSpecialistAccountingStatements,
  useSpecialistUtilityBills,
} from '../hooks/useDocuments';
import type { KnowledgeAgentResponse, KnowledgeAgentRunDetail, KnowledgeAgentTraceStep, KnowledgeAssertion } from '../types';

function formatDate(value: string | null | undefined) {
  if (!value) return 'n/d';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString('it-IT');
}

function formatCurrency(value: number | null | undefined) {
  if (typeof value !== 'number') return 'n/d';
  return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(value);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return 'n/d';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('it-IT');
}

function formatAssertionValue(assertion: KnowledgeAssertion) {
  return assertion.object_node_label ?? assertion.value_text ?? 'n/d';
}

const tabClass = (current: boolean) =>
  `rounded-full border px-4 py-2 text-sm transition ${
    current
      ? 'border-cyan-300/35 bg-cyan-400/15 text-cyan-100'
      : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
    }`;

/* ── Agent Panel ── */

interface AgentPanelProps {
  onOpenDocument: (documentId: string) => void;
}

export function AgentPanel({ onOpenDocument }: AgentPanelProps) {
  const [draft, setDraft] = useState('');
  const [allowVision, setAllowVision] = useState(false);
  const [activeTab, setActiveTab] = useState<'chat' | 'history'>('chat');
  const [messages, setMessages] = useState<Array<{ id: string; role: 'user' | 'assistant'; content: string; result?: KnowledgeAgentResponse | KnowledgeAgentRunDetail }>>([]);
  const [liveSteps, setLiveSteps] = useState<KnowledgeAgentTraceStep[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const runs = useKnowledgeAgentRuns(50);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, liveSteps.length, isStreaming]);

  const ask = async () => {
    const question = draft.trim();
    if (!question || isStreaming) return;
    const history = messages
      .filter((message) => message.content.trim())
      .slice(-10)
      .map((message) => ({ role: message.role, content: message.content }));
    const userMessage = { id: crypto.randomUUID(), role: 'user' as const, content: question };
    const assistantId = crypto.randomUUID();
    setDraft('');
    setActiveTab('chat');
    setStreamError(null);
    setLiveSteps([]);
    setIsStreaming(true);
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: 'assistant', content: 'Sto interrogando l’archivio...', result: undefined },
    ]);
    try {
      const response = await streamKnowledgeAgent(
        { question, allow_vision: allowVision, max_steps: 16, history },
        (event) => {
          if (event.type === 'step') {
            setLiveSteps((current) => [...current, event.payload as KnowledgeAgentTraceStep]);
          }
          if (event.type === 'final') {
            const finalResponse = event.payload as KnowledgeAgentResponse;
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId ? { ...message, content: finalResponse.answer, result: finalResponse } : message,
              ),
            );
          }
        },
      );
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, content: response.answer, result: response } : message,
        ),
      );
      runs.refetch();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStreamError(message);
      setMessages((current) =>
        current.map((item) => (item.id === assistantId ? { ...item, content: `Errore: ${message}` } : item)),
      );
    } finally {
      setIsStreaming(false);
    }
  };

  const loadRunIntoChat = async (run: KnowledgeAgentRunDetail | undefined) => {
    if (!run) return;
    setActiveTab('chat');
    setLiveSteps([]);
    setMessages([
      { id: `${run.id}-q`, role: 'user', content: run.question },
      { id: `${run.id}-a`, role: 'assistant', content: run.answer, result: run },
    ]);
  };

  return (
    <div className="flex h-full min-h-0 flex-col rounded-2xl border border-white/10 bg-slate-950/35">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4">
        <div>
          <p className="text-sm font-semibold text-white">Dialogo con l'archivio</p>
          <p className="mt-1 text-xs text-slate-400">Chat continuativa con trace tool in tempo reale e fonti citate.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setActiveTab('chat')} className={tabClass(activeTab === 'chat')}>Chat</button>
          <button onClick={() => setActiveTab('history')} className={tabClass(activeTab === 'history')}>Storico</button>
          <button
            onClick={() => {
              setMessages([]);
              setLiveSteps([]);
              setStreamError(null);
            }}
            disabled={isStreaming || messages.length === 0}
            className="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/10 disabled:opacity-40"
          >
            Nuova chat
          </button>
        </div>
      </div>

      {activeTab === 'history' ? (
        <AgentHistoryPanel
          runs={runs}
          onLoad={loadRunIntoChat}
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {messages.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] p-6 text-sm text-slate-400">
                Fai una domanda. Le successive saranno inviate insieme al contesto della chat corrente.
              </div>
            ) : (
              <div className="space-y-4">
                {messages.map((message, index) => (
                  <ChatMessageCard
                    key={message.id}
                    message={message}
                    liveSteps={index === messages.length - 1 && isStreaming ? liveSteps : []}
                    onOpenDocument={onOpenDocument}
                  />
                ))}
              </div>
            )}
            {streamError && (
              <p className="mt-3 rounded-xl border border-rose-300/25 bg-rose-400/10 p-3 text-sm text-rose-100">
                {streamError}
              </p>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-white/10 p-4">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                  ask();
                }
              }}
              placeholder="Scrivi un messaggio. Ctrl/Cmd+Invio per inviare."
              className="min-h-[5.5rem] w-full resize-none rounded-2xl border border-white/10 bg-slate-900 p-3 text-sm text-white outline-none placeholder:text-slate-500"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-start gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={allowVision}
                  onChange={(event) => setAllowVision(event.target.checked)}
                  className="mt-0.5"
                />
                <span>Consenti richieste vision quando l'OCR non basta.</span>
              </label>
              <button
                onClick={ask}
                disabled={isStreaming || draft.trim().length < 3}
                className="rounded-full border border-cyan-300/35 bg-cyan-400/15 px-5 py-2 text-sm text-cyan-100 disabled:opacity-40"
              >
                {isStreaming ? 'Ragionamento in corso...' : 'Invia'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ChatMessageCard({
  message,
  liveSteps,
  onOpenDocument,
}: {
  message: { role: 'user' | 'assistant'; content: string; result?: KnowledgeAgentResponse | KnowledgeAgentRunDetail };
  liveSteps: KnowledgeAgentTraceStep[];
  onOpenDocument: (documentId: string) => void;
}) {
  const result = message.result;
  return (
    <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[min(920px,92%)] rounded-2xl border p-4 ${
          message.role === 'user'
            ? 'border-cyan-300/30 bg-cyan-400/15 text-cyan-50'
            : 'border-white/10 bg-slate-900/80 text-slate-100'
        }`}
      >
        <div className="mb-2 text-[11px] uppercase tracking-wide text-slate-400">
          {message.role === 'user' ? 'Tu' : 'Agente'}
          {result?.status && <span className="ml-2 normal-case text-slate-500">{result.status}</span>}
          {result?.model && <span className="ml-2 normal-case text-slate-500">{result.model}</span>}
        </div>
        <p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>
        {result && <AgentResultDetails result={result} onOpenDocument={onOpenDocument} />}
        {liveSteps.length > 0 && <AgentTrace steps={liveSteps} compact />}
      </div>
    </div>
  );
}

function AgentResultDetails({
  result,
  onOpenDocument,
}: {
  result: KnowledgeAgentResponse | KnowledgeAgentRunDetail;
  onOpenDocument: (documentId: string) => void;
}) {
  return (
    <div className="mt-4 space-y-3">
      {result.citations.length > 0 && (
        <section>
          <p className="mb-2 text-xs font-semibold text-white">Fonti</p>
          <div className="grid gap-2 md:grid-cols-2">
            {result.citations.map((citation, index) => (
              <button
                key={`${citation.document_unit_id ?? citation.document_id}-${index}`}
                onClick={() => citation.document_id && onOpenDocument(citation.document_id)}
                disabled={!citation.document_id}
                className="rounded-xl border border-white/10 bg-white/5 p-3 text-left text-sm hover:bg-white/10 disabled:opacity-60"
              >
                <p className="truncate text-cyan-200">{citation.title || citation.original_filename || 'Documento'}</p>
                <p className="mt-1 text-xs text-slate-400">
                  Pagine {citation.page_from ?? '?'}-{citation.page_to ?? citation.page_from ?? '?'}
                </p>
                {citation.quote && <p className="mt-2 line-clamp-3 text-xs text-slate-300">{citation.quote}</p>}
              </button>
            ))}
          </div>
        </section>
      )}
      {result.vision_requests.length > 0 && (
        <section className="rounded-2xl border border-amber-300/20 bg-amber-400/10 p-3">
          <p className="text-sm font-semibold text-amber-100">Pagine richieste per vision</p>
          <div className="mt-2 space-y-2">
            {result.vision_requests.map((request) => (
              <button
                key={`${request.document_id}-${request.page_number}`}
                onClick={() => onOpenDocument(request.document_id)}
                className="block w-full rounded-xl border border-amber-300/15 bg-slate-950/25 p-3 text-left text-xs text-amber-50"
              >
                Documento {request.document_id}, pagina {request.page_number}
                {request.reason && <span className="mt-1 block text-amber-100/80">{request.reason}</span>}
              </button>
            ))}
          </div>
        </section>
      )}
      <AgentTrace steps={result.tool_trace} />
    </div>
  );
}

function AgentTrace({ steps, compact = false }: { steps: KnowledgeAgentTraceStep[]; compact?: boolean }) {
  if (steps.length === 0) return null;
  return (
    <section>
      <p className="mb-2 text-xs font-semibold text-white">{compact ? 'Step in corso' : 'Trace tool'}</p>
      <div className="space-y-2">
        {steps.map((step) => (
          <details key={`${step.step}-${step.action}`} className="rounded-xl border border-white/10 bg-white/5 p-3" open={compact}>
            <summary className="cursor-pointer text-sm text-slate-200">
              #{step.step} {step.action}
              {step.error && <span className="ml-2 text-rose-200">errore</span>}
            </summary>
            {step.reasoning && <p className="mt-2 text-xs text-slate-400">{step.reasoning}</p>}
            {!compact && (
              <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-slate-950/70 p-3 text-xs text-slate-300">
                {JSON.stringify({ input: step.input, output: step.output, error: step.error }, null, 2)}
              </pre>
            )}
          </details>
        ))}
      </div>
    </section>
  );
}

function AgentHistoryPanel({
  runs,
  onLoad,
}: {
  runs: ReturnType<typeof useKnowledgeAgentRuns>;
  onLoad: (run: KnowledgeAgentRunDetail | undefined) => void;
}) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const selectedRun = useMemo(
    () => runs.data?.find((run) => run.id === selectedRunId),
    [runs.data, selectedRunId],
  );
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-white">Ultimi dialoghi</p>
        <button
          onClick={() => runs.refetch()}
          className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300 hover:bg-white/10"
        >
          Aggiorna
        </button>
      </div>
      {runs.isLoading ? (
        <p className="text-xs text-slate-400">Caricamento storico...</p>
      ) : runs.data?.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {runs.data.map((run) => (
            <button
              key={run.id}
              onClick={async () => {
                setSelectedRunId(run.id);
                setLoadingRunId(run.id);
                try {
                  onLoad(await getKnowledgeAgentRun(run.id));
                } finally {
                  setLoadingRunId(null);
                }
              }}
              className={`rounded-xl border p-3 text-left hover:bg-white/10 ${
                selectedRun?.id === run.id ? 'border-cyan-300/35 bg-cyan-400/10' : 'border-white/10 bg-white/5'
              }`}
            >
              <p className="line-clamp-3 text-sm font-medium text-slate-100">{run.question}</p>
              <p className="mt-2 text-[11px] text-slate-500">
                {formatDateTime(run.created_at)} · {run.status} · {run.tool_step_count} tool · {run.citation_count} fonti
                {run.duration_ms !== null ? ` · ${run.duration_ms} ms` : ''}
              </p>
              {loadingRunId === run.id && <p className="mt-2 text-xs text-cyan-200">Apro dialogo...</p>}
              <p className="mt-2 line-clamp-3 text-xs text-slate-400">{run.answer}</p>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-400">Nessun dialogo salvato.</p>
      )}
    </div>
  );
}

/* ── Facts Panel ── */

interface FactsPanelProps {
  onOpenDocument: (documentId: string) => void;
  deferredSearch: string;
}

export const FactsPanel = memo(function FactsPanel({ onOpenDocument, deferredSearch }: FactsPanelProps) {
  const [nodeKindFilter, setNodeKindFilter] = useState('all');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showNodeDetail, setShowNodeDetail] = useState(false);

  const nodesQuery = useKnowledgeNodes({ query: deferredSearch || undefined, nodeKind: nodeKindFilter, limit: 60 }, true);
  const nodes = nodesQuery.data ?? [];
  const nodesKey = useMemo(() => nodes.map((n) => n.id).join(','), [nodes]);
  const assertionsQuery = useKnowledgeAssertions({ query: deferredSearch || undefined, nodeId: selectedNodeId || undefined, limit: 80 }, true);
  const nodeDetail = useKnowledgeNode(selectedNodeId);

  useEffect(() => {
    if (!nodes.length) { setSelectedNodeId(null); return; }
    if (!selectedNodeId || !nodes.some((n) => n.id === selectedNodeId)) setSelectedNodeId(nodes[0].id);
  }, [nodesKey]);

  useEffect(() => {
    if (!showNodeDetail) return;
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setShowNodeDetail(false); };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showNodeDetail]);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {[['all', 'Tutti'], ['organization', 'Organizzazioni'], ['address', 'Indirizzi'], ['person', 'Persone'], ['place', 'Luoghi']].map(([value, label]) => (
            <button key={value} onClick={() => setNodeKindFilter(value)} className={tabClass(nodeKindFilter === value)}>{label}</button>
          ))}
        </div>
        <button onClick={() => setShowNodeDetail(true)} disabled={!selectedNodeId} className="rounded-full border border-indigo-300/25 bg-indigo-400/15 px-4 py-2 text-sm text-indigo-100 disabled:opacity-40">Dettaglio e fonti</button>
      </div>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-3">
          {nodesQuery.isLoading ? <p className="text-sm text-slate-400">Caricamento nodi...</p> : nodes.length === 0 ? <p className="text-sm text-slate-400">Nessun nodo trovato.</p> : (
            <div className="space-y-2">
              {nodes.map((node) => (
                <button key={node.id} onClick={() => setSelectedNodeId(node.id)} className={`w-full rounded-xl border p-3 text-left ${node.id === selectedNodeId ? 'border-indigo-300/35 bg-indigo-400/15' : 'border-white/10 bg-white/5 hover:bg-white/10'}`}>
                  <p className="truncate text-sm font-medium text-white">{node.label}</p>
                  <p className="mt-1 text-xs text-slate-400">{node.node_kind} · {node.document_count} documenti · {node.alias_count} alias</p>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-3">
          {assertionsQuery.isLoading ? <p className="text-sm text-slate-400">Caricamento fatti...</p> : assertionsQuery.data?.length ? (
            <div className="grid gap-2 md:grid-cols-2">
              {assertionsQuery.data.map((a) => (
                <article key={a.id} className="rounded-xl border border-white/10 bg-white/5 p-3">
                  <div className="flex justify-between gap-2 text-xs">
                    <span className="uppercase tracking-wide text-indigo-200">{a.predicate_label}</span>
                    <span className="text-slate-500">{a.source_type}</span>
                  </div>
                  <p className="mt-2 text-sm text-white">{formatAssertionValue(a)}</p>
                  {a.confidence !== null && <p className="mt-1 text-xs text-slate-400">{Math.round(a.confidence * 100)}% confidenza</p>}
                </article>
              ))}
            </div>
          ) : <p className="text-sm text-slate-400">Nessun fatto collegato.</p>}
        </div>
      </div>
      {showNodeDetail && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/75 p-4" onClick={() => setShowNodeDetail(false)}>
          <div className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-3xl border border-indigo-300/20 bg-slate-900 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-lg font-semibold text-white">{nodeDetail.data?.node.label ?? 'Dettaglio nodo'}</p>
              <button onClick={() => setShowNodeDetail(false)} className={tabClass(false)}>Chiudi</button>
            </div>
            <div className="min-h-0 overflow-y-auto">
              {nodeDetail.data && (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2">{nodeDetail.data.aliases.map((a) => <span key={a} className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">{a}</span>)}</div>
                  <div className="grid gap-2 md:grid-cols-2">
                    {nodeDetail.data.documents.map((d) => (
                      <button key={d.document_unit_id} onClick={() => onOpenDocument(d.document_id)} className="rounded-xl border border-white/10 bg-white/5 p-3 text-left hover:bg-white/10">
                        <p className="truncate text-sm text-cyan-200">{d.original_filename}</p>
                        <p className="mt-1 text-xs text-slate-400">Pagine {d.start_page}-{d.end_page}</p>
                        {d.summary && <p className="mt-2 line-clamp-2 text-xs text-slate-300">{d.summary}</p>}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Specialists Panel ── */

interface SpecialistsPanelProps {
  onOpenDocument: (documentId: string) => void;
  deferredSearch: string;
}

export const SpecialistsPanel = memo(function SpecialistsPanel({ onOpenDocument, deferredSearch }: SpecialistsPanelProps) {
  const [specialistPanel, setSpecialistPanel] = useState<'accounting' | 'utility'>('accounting');
  const [utilityPaymentFilter, setUtilityPaymentFilter] = useState('all');
  const [utilityOverdueOnly, setUtilityOverdueOnly] = useState(false);
  const [accountingTypeFilter, setAccountingTypeFilter] = useState('all');
  const [accountingCheckFilter, setAccountingCheckFilter] = useState('all');

  const accountingPanelActive = specialistPanel === 'accounting';
  const utilityPanelActive = specialistPanel === 'utility';

  const utilityLens = useSpecialistUtilityBills({ query: deferredSearch || undefined, paymentStatus: utilityPaymentFilter, overdueOnly: utilityOverdueOnly, limit: 40 }, utilityPanelActive);
  const accountingLens = useSpecialistAccountingStatements({ query: deferredSearch || undefined, statementType: accountingTypeFilter, checkStatus: accountingCheckFilter, limit: 40 }, accountingPanelActive);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <button onClick={() => setSpecialistPanel('accounting')} className={tabClass(specialistPanel === 'accounting')}>Rendiconti ({accountingLens.data?.total ?? 0})</button>
        <button onClick={() => setSpecialistPanel('utility')} className={tabClass(specialistPanel === 'utility')}>Bollette ({utilityLens.data?.total ?? 0})</button>
        {specialistPanel === 'accounting' ? (
          <>
            <select value={accountingTypeFilter} onChange={(e) => setAccountingTypeFilter(e.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
              <option value="all">Tutti i tipi</option>
              <option value="rendiconto_composito">Rendiconto composito</option>
              <option value="bilancio_preventivo">Bilancio preventivo</option>
              <option value="riparto_spese">Riparto spese</option>
              <option value="rendiconto">Rendiconto</option>
              <option value="estratto_contabile">Estratto contabile</option>
            </select>
            <select value={accountingCheckFilter} onChange={(e) => setAccountingCheckFilter(e.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
              <option value="all">Tutti i check</option>
              <option value="pass">Passati</option>
              <option value="fail">Falliti</option>
              <option value="unknown">Ignoto</option>
            </select>
          </>
        ) : (
          <>
            <select value={utilityPaymentFilter} onChange={(e) => setUtilityPaymentFilter(e.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
              <option value="all">Tutti i pagamenti</option>
              <option value="paid">Pagate</option>
              <option value="unpaid">Non pagate</option>
              <option value="unknown">Ignoto</option>
            </select>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" checked={utilityOverdueOnly} onChange={(e) => setUtilityOverdueOnly(e.target.checked)} /> Scadute
            </label>
          </>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-3">
        {specialistPanel === 'accounting' ? (
          accountingLens.isLoading ? <p className="text-sm text-slate-400">Caricamento rendiconti...</p> : accountingLens.data?.items.length ? (
            <div className="grid gap-3 xl:grid-cols-2">
              {accountingLens.data.items.map((s) => (
                <article key={s.result_id} className="rounded-xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium text-white">{s.statement_type ?? 'Rendiconto'}</p>
                      <p className="mt-1 truncate text-xs text-slate-400">{s.original_filename}</p>
                    </div>
                    <span className={s.has_failed_checks ? 'text-xs text-rose-200' : 'text-xs text-emerald-200'}>{s.has_failed_checks ? 'da verificare' : 'coerente'}</span>
                  </div>
                  <p className="mt-3 line-clamp-2 text-sm text-slate-300">{s.summary ?? 'Nessun riassunto.'}</p>
                  <p className="mt-3 text-xs text-slate-300">{formatDate(s.accounting_period_from)} - {formatDate(s.accounting_period_to)} · {s.section_count} sezioni · {s.table_count} tabelle</p>
                  {s.sections.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {s.sections.slice(0, 6).map((sec) => <span key={String(sec.section_id)} className="rounded-full border border-white/10 bg-slate-950/50 px-2 py-1 text-xs text-slate-300">{String(sec.label || 'Sezione')} · {String(sec.table_count || 0)}</span>)}
                      {s.sections.length > 6 && <span className="rounded-full border border-white/10 bg-slate-950/50 px-2 py-1 text-xs text-slate-400">+{s.sections.length - 6}</span>}
                    </div>
                  )}
                  <div className="mt-3 flex gap-2">
                    {s.document_id && <button onClick={() => onOpenDocument(s.document_id!)} className={tabClass(false)}>Documento</button>}
                    <a href={`/api/knowledge/specialist-results/${s.result_id}/export?format=json`} target="_blank" rel="noreferrer" className={tabClass(false)}>JSON</a>
                    <a href={`/api/knowledge/specialist-results/${s.result_id}/export?format=csv`} className={tabClass(false)}>CSV</a>
                  </div>
                </article>
              ))}
            </div>
          ) : <p className="text-sm text-slate-400">Nessun rendiconto trovato.</p>
        ) : (
          utilityLens.isLoading ? <p className="text-sm text-slate-400">Caricamento bollette...</p> : utilityLens.data?.items.length ? (
            <div className="grid gap-3 xl:grid-cols-2">
              {utilityLens.data.items.map((b) => (
                <article key={b.result_id} className="rounded-xl border border-white/10 bg-white/5 p-4">
                  <div className="flex justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium text-white">{b.issuer ?? 'Emittente non disponibile'}</p>
                      <p className="mt-1 truncate text-xs text-slate-400">{b.original_filename}</p>
                    </div>
                    <p className="font-medium text-white">{formatCurrency(b.total_amount)}</p>
                  </div>
                  <p className="mt-3 text-sm text-slate-300">Scadenza {formatDate(b.due_date)} · {b.payment_status ?? 'unknown'}</p>
                  <div className="mt-3 flex gap-2">
                    {b.document_id && <button onClick={() => onOpenDocument(b.document_id!)} className={tabClass(false)}>Documento</button>}
                    <a href={`/api/knowledge/specialist-results/${b.result_id}/export?format=json`} target="_blank" rel="noreferrer" className={tabClass(false)}>JSON</a>
                  </div>
                </article>
              ))}
            </div>
          ) : <p className="text-sm text-slate-400">Nessuna bolletta valida trovata.</p>
        )}
      </div>
    </div>
  );
});

/* ── Topics Panel ── */

interface TopicsPanelProps {
  onOpenDocument: (documentId: string) => void;
  deferredSearch: string;
  includeInactive: boolean;
}

export const TopicsPanel = memo(function TopicsPanel({ onOpenDocument, deferredSearch, includeInactive }: TopicsPanelProps) {
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const [topicClassFilter, setTopicClassFilter] = useState('all');
  const [topicKindFilter, setTopicKindFilter] = useState('all');

  const topicsQuery = useKnowledgeTopics(includeInactive);
  const topics = topicsQuery.data ?? [];
  const topicSearch = useKnowledgeSearch(deferredSearch, { includeInactive, topicClass: topicClassFilter, topicKind: topicKindFilter, limit: 60 });
  const topicDetail = useKnowledgeTopic(selectedTopicId);
  const consolidate = useRunKnowledgeConsolidation();

  const topicClasses: string[] = useMemo(
    () => Array.from(new Set(topics.map((t) => t.topic_class))).sort(),
    [topics],
  );
  const topicKinds: string[] = useMemo(
    () => Array.from(new Set(topics.map((t) => t.topic_kind))).sort(),
    [topics],
  );

  const visibleTopics = useMemo(() => {
    const query = deferredSearch.toLowerCase();
    const matchingIds = query.length >= 2 && topicSearch.data ? new Set(topicSearch.data.topics.map((hit) => hit.topic.id)) : null;
    return topics.filter((topic) => {
      if (topicClassFilter !== 'all' && topic.topic_class !== topicClassFilter) return false;
      if (topicKindFilter !== 'all' && topic.topic_kind !== topicKindFilter) return false;
      if (!query) return true;
      if (matchingIds) return matchingIds.has(topic.id);
      return topic.title.toLowerCase().includes(query) || topic.slug.toLowerCase().includes(query);
    });
  }, [deferredSearch, topicClassFilter, topicKindFilter, topicSearch.data, topics]);
  const visibleTopicsKey = useMemo(() => visibleTopics.map((t) => t.id).join(','), [visibleTopics]);

  useEffect(() => {
    if (!visibleTopics.length) { setSelectedTopicId(null); return; }
    if (!selectedTopicId || !visibleTopics.some((t) => t.id === selectedTopicId)) setSelectedTopicId(visibleTopics[0].id);
  }, [visibleTopicsKey]);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <select value={topicClassFilter} onChange={(e) => setTopicClassFilter(e.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
          <option value="all">Tutte le classi</option>
          {topicClasses.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <select value={topicKindFilter} onChange={(e) => setTopicKindFilter(e.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
          <option value="all">Tutti i tipi</option>
          {topicKinds.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <button onClick={() => consolidate.mutate()} disabled={consolidate.isPending} className="rounded-full border border-cyan-300/25 bg-cyan-400/15 px-4 py-2 text-sm text-cyan-100 disabled:opacity-50">
          {consolidate.isPending ? 'Elaborazione...' : 'Consolida'}
        </button>
        {consolidate.data && <span className="text-xs text-emerald-200">Uniti {consolidate.data.topics_merged} topic</span>}
      </div>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-2">
          {visibleTopics.map((topic) => (
            <button key={topic.id} onClick={() => setSelectedTopicId(topic.id)} className={`mb-2 w-full rounded-xl border p-3 text-left ${topic.id === selectedTopicId ? 'border-cyan-300/30 bg-cyan-400/10' : 'border-white/10 bg-white/5'}`}>
              <p className="truncate text-sm font-medium text-white">{topic.title}</p>
              <p className="mt-1 text-xs text-slate-400">{topic.topic_kind} · {topic.assignment_count} assegnazioni</p>
            </button>
          ))}
        </div>
        <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-4">
          {topicDetail.isLoading ? <p className="text-sm text-slate-400">Caricamento...</p> : topicDetail.data ? (
            <div>
              <p className="text-lg font-semibold text-white">{topicDetail.data.topic.title}</p>
              <p className="mt-1 text-sm text-slate-400">{topicDetail.data.topic.topic_kind} · {topicDetail.data.topic.topic_class} · {topicDetail.data.related_documents.length} documenti</p>
              {topicDetail.data.topic.description && <p className="mt-3 text-sm text-slate-300">{topicDetail.data.topic.description}</p>}
              <div className="mt-4 grid gap-2 xl:grid-cols-2">
                {topicDetail.data.related_documents.map((d) => (
                  <button key={d.document_unit_id} onClick={() => onOpenDocument(d.document_id)} className="rounded-xl border border-white/10 bg-white/5 p-3 text-left hover:bg-white/10">
                    <p className="truncate text-sm text-cyan-200">{d.original_filename}</p>
                    <p className="mt-1 text-xs text-slate-400">Pagine {d.start_page}-{d.end_page}</p>
                    {d.summary && <p className="mt-2 line-clamp-2 text-xs text-slate-300">{d.summary}</p>}
                  </button>
                ))}
              </div>
            </div>
          ) : <p className="text-sm text-slate-400">Seleziona un topic.</p>}
        </div>
      </div>
    </div>
  );
});

/* ── Entities Panel ── */

interface EntitiesPanelProps {
  onOpenDocument: (documentId: string) => void;
  deferredSearch: string;
}

export const EntitiesPanel = memo(function EntitiesPanel({ onOpenDocument, deferredSearch }: EntitiesPanelProps) {
  const [entityTypeFilter, setEntityTypeFilter] = useState('all');
  const [selectedEntityKey, setSelectedEntityKey] = useState<string | null>(null);
  const [selectedEntityType, setSelectedEntityType] = useState<string | null>(null);
  const [canonicalEntityId, setCanonicalEntityId] = useState('');
  const [newCanonicalValue, setNewCanonicalValue] = useState('');
  const [newCanonicalDisplay, setNewCanonicalDisplay] = useState('');

  const entityQuery = useKnowledgeEntities({ query: deferredSearch || undefined, entityType: entityTypeFilter, limit: 40 }, true);
  const entities = entityQuery.data ?? [];
  const entitiesKey = useMemo(() => entities.map((e) => `${e.entity_type}:${e.entity_key}`).join(','), [entities]);
  const canonicalQuery = useCanonicalEntities({ query: deferredSearch || undefined, entityType: entityTypeFilter, limit: 40 }, true);
  const entityDetail = useKnowledgeEntityDetail(selectedEntityType, selectedEntityKey);
  const mergeCanonicalEntity = useMergeCanonicalEntity();

  useEffect(() => {
    if (!entities.length) { setSelectedEntityKey(null); setSelectedEntityType(null); return; }
    if (!selectedEntityKey || !selectedEntityType || !entities.some((e) => e.entity_key === selectedEntityKey && e.entity_type === selectedEntityType)) {
      setSelectedEntityKey(entities[0].entity_key);
      setSelectedEntityType(entities[0].entity_type);
    }
  }, [entitiesKey]);

  const entityDetailKey = entityDetail.data ? `${entityDetail.data.entity_type}:${entityDetail.data.entity_key}` : null;

  useEffect(() => {
    if (!entityDetailKey) return;
    setNewCanonicalValue(entityDetail.data!.entity_key);
    setNewCanonicalDisplay(entityDetail.data!.display_value);
    setCanonicalEntityId('');
  }, [entityDetailKey]);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="shrink-0">
        <select value={entityTypeFilter} onChange={(e) => setEntityTypeFilter(e.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
          <option value="all">Tutte le entità</option>
          <option value="organizzazione">Organizzazioni</option>
          <option value="indirizzo">Indirizzi</option>
          <option value="persona">Persone</option>
          <option value="luogo">Luoghi</option>
        </select>
      </div>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-2">
          {entityQuery.isLoading ? <p className="p-3 text-sm text-slate-400">Caricamento...</p> : entities.map((entity) => (
            <button key={`${entity.entity_type}:${entity.entity_key}`} onClick={() => { setSelectedEntityType(entity.entity_type); setSelectedEntityKey(entity.entity_key); }} className={`mb-2 w-full rounded-xl border p-3 text-left ${entity.entity_key === selectedEntityKey && entity.entity_type === selectedEntityType ? 'border-violet-300/30 bg-violet-400/10' : 'border-white/10 bg-white/5'}`}>
              <p className="truncate text-sm text-white">{entity.display_value}</p>
              <p className="mt-1 text-xs text-slate-400">{entity.document_count} documenti · {entity.mention_count} mention</p>
            </button>
          ))}
        </div>
        <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-4">
          {entityDetail.data ? (
            <div className="space-y-4">
              <div>
                <p className="text-lg font-semibold text-white">{entityDetail.data.display_value}</p>
                <p className="text-sm text-slate-400">{entityDetail.data.entity_type} · {entityDetail.data.document_count} documenti</p>
              </div>
              <div className="rounded-xl border border-violet-300/20 bg-violet-400/10 p-3">
                <p className="mb-3 text-xs uppercase tracking-wide text-violet-100">Canonizzazione</p>
                <div className="grid gap-2 md:grid-cols-2">
                  <select value={canonicalEntityId} onChange={(e) => setCanonicalEntityId(e.target.value)} className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm">
                    <option value="">Nuova entità canonica</option>
                    {(canonicalQuery.data ?? []).filter((item) => item.entity_type === entityDetail.data?.entity_type).map((item) => <option key={item.id} value={item.id}>{item.display_value}</option>)}
                  </select>
                  {!canonicalEntityId && <input value={newCanonicalDisplay} onChange={(e) => setNewCanonicalDisplay(e.target.value)} className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm" />}
                  {!canonicalEntityId && <input value={newCanonicalValue} onChange={(e) => setNewCanonicalValue(e.target.value)} className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm md:col-span-2" />}
                </div>
                <button onClick={() => mergeCanonicalEntity.mutate({
                  entity_type: entityDetail.data!.entity_type,
                  entity_keys: [entityDetail.data!.entity_key],
                  target_canonical_entity_id: canonicalEntityId || undefined,
                  create_canonical_entity: canonicalEntityId ? undefined : { entity_type: entityDetail.data!.entity_type, canonical_value: newCanonicalValue || entityDetail.data!.entity_key, display_value: newCanonicalDisplay || entityDetail.data!.display_value },
                })} className="mt-3 rounded-full border border-violet-300/25 bg-violet-400/20 px-4 py-2 text-sm text-violet-50">Salva canonizzazione</button>
              </div>
              <div className="grid gap-2 xl:grid-cols-2">
                {entityDetail.data.documents.map((d) => (
                  <button key={d.document_unit_id} onClick={() => onOpenDocument(d.document_id)} className="rounded-xl border border-white/10 bg-white/5 p-3 text-left">
                    <p className="truncate text-sm text-cyan-200">{d.original_filename}</p>
                    <p className="mt-1 text-xs text-slate-400">Pagine {d.start_page}-{d.end_page}</p>
                  </button>
                ))}
              </div>
            </div>
          ) : <p className="text-sm text-slate-400">Seleziona un'entità.</p>}
        </div>
      </div>
    </div>
  );
});

/* ── Reviews Panel ── */

interface ReviewsPanelProps {
  deferredSearch: string;
}

export const ReviewsPanel = memo(function ReviewsPanel({ deferredSearch: _deferredSearch }: ReviewsPanelProps) {
  const [graphReviewAuthor, setGraphReviewAuthor] = useState('');
  const [graphReviewNotes, setGraphReviewNotes] = useState<Record<string, string>>({});
  const graphSuggestions = useGraphConsolidationSuggestions(12, true);
  const reviewGraphSuggestion = useReviewGraphConsolidationSuggestion();

  return (
    <div className="flex h-full flex-col gap-3">
      <input value={graphReviewAuthor} onChange={(e) => setGraphReviewAuthor(e.target.value)} placeholder="Revisore (facoltativo)" className="shrink-0 rounded-xl border border-white/10 bg-slate-950/50 px-3 py-2 text-sm" />
      <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto xl:grid-cols-3">
        {[
          { axis: 'subject', label: 'Soggetti', items: graphSuggestions.data?.subject ?? [] },
          { axis: 'document_family', label: 'Famiglie documento', items: graphSuggestions.data?.document_family ?? [] },
          { axis: 'case_or_issue', label: 'Pratiche', items: graphSuggestions.data?.case_or_issue ?? [] },
        ].map((group) => (
          <div key={group.axis} className="rounded-2xl border border-white/10 bg-slate-950/35 p-3">
            <p className="mb-3 text-sm font-semibold text-white">{group.label} ({group.items.length})</p>
            <div className="space-y-3">
              {group.items.map((item) => {
                const key = `${group.axis}-${item.source_topic.id}-${item.target_topic.id}`;
                return (
                  <article key={key} className="rounded-xl border border-white/10 bg-white/5 p-3">
                    <p className="text-xs text-cyan-200">Score {item.score.toFixed(2)} · {item.shared_document_count} documenti comuni</p>
                    <p className="mt-2 text-sm text-white">{item.target_topic.title}</p>
                    <p className="mt-1 text-xs text-slate-400">Candidato: {item.source_topic.title}</p>
                    <p className="mt-2 line-clamp-3 text-xs text-slate-300">{item.rationale}</p>
                    <textarea value={graphReviewNotes[key] ?? ''} onChange={(e) => setGraphReviewNotes((v) => ({ ...v, [key]: e.target.value }))} placeholder="Nota" className="mt-3 h-16 w-full rounded-lg border border-white/10 bg-slate-950/60 p-2 text-xs" />
                    <div className="mt-2 flex flex-wrap gap-2">
                      {[
                        ['merge_into_target', 'Unisci', 'border-emerald-300/25 text-emerald-100'],
                        ['dismiss', 'Ignora', 'border-white/10 text-slate-200'],
                        ['mark_same_subject_different_family', 'Separa', 'border-amber-300/25 text-amber-100'],
                        ['convert_to_secondary_relationship', 'Secondaria', 'border-fuchsia-300/25 text-fuchsia-100'],
                      ].map(([action, label, colors]) => (
                        <button key={action} onClick={() => reviewGraphSuggestion.mutate({
                          axis: group.axis as 'subject' | 'document_family' | 'case_or_issue',
                          source_topic_id: item.source_topic.id,
                          target_topic_id: item.target_topic.id,
                          action: action as 'merge_into_target' | 'dismiss' | 'mark_same_subject_different_family' | 'convert_to_secondary_relationship',
                          note: graphReviewNotes[key] || null,
                          acted_by: graphReviewAuthor || null,
                        })} className={`rounded-full border px-3 py-1.5 text-xs ${colors}`}>{label}</button>
                      ))}
                    </div>
                  </article>
                );
              })}
              {!group.items.length && <p className="text-sm text-slate-400">Nessuna proposta.</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});
