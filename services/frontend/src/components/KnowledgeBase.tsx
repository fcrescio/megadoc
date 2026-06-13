import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  useCanonicalEntities,
  useContextAccountingComparison,
  useContextAccountingSubjects,
  useGraphConsolidationSuggestions,
  useKnowledgeAssertions,
  useKnowledgeEntities,
  useKnowledgeEntityDetail,
  useKnowledgeGraphStats,
  useKnowledgeContexts,
  useKnowledgeNode,
  useKnowledgeNodes,
  useKnowledgeSearch,
  useMergeCanonicalEntity,
  useKnowledgeTopic,
  useKnowledgeTopics,
  useReviewGraphConsolidationSuggestion,
  useRunKnowledgeConsolidation,
  useSpecialistAccountingStatements,
  useSpecialistUtilityBills,
  useTopicProposals,
} from '../hooks/useDocuments';
import type { KnowledgeAssertion } from '../types';
import AccountingReconciliationModal from './AccountingReconciliationModal';
import ProposalList from './ProposalList';

interface Props {
  onOpenDocument: (documentId: string) => void;
}

type Panel = 'comparisons' | 'facts' | 'specialists' | 'topics' | 'entities' | 'reviews';
type SpecialistPanel = 'accounting' | 'utility';

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

function formatAssertionValue(assertion: KnowledgeAssertion) {
  return assertion.object_node_label ?? assertion.value_text ?? 'n/d';
}

function KnowledgeBase({ onOpenDocument }: Props) {
  const [panel, setPanel] = useState<Panel>('comparisons');
  const [specialistPanel, setSpecialistPanel] = useState<SpecialistPanel>('accounting');
  const [searchInput, setSearchInput] = useState('');
  const [includeInactive, setIncludeInactive] = useState(false);
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const [topicClassFilter, setTopicClassFilter] = useState('all');
  const [topicKindFilter, setTopicKindFilter] = useState('all');
  const [entityTypeFilter, setEntityTypeFilter] = useState('all');
  const [selectedEntityKey, setSelectedEntityKey] = useState<string | null>(null);
  const [selectedEntityType, setSelectedEntityType] = useState<string | null>(null);
  const [canonicalEntityId, setCanonicalEntityId] = useState('');
  const [newCanonicalValue, setNewCanonicalValue] = useState('');
  const [newCanonicalDisplay, setNewCanonicalDisplay] = useState('');
  const [nodeKindFilter, setNodeKindFilter] = useState('all');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showNodeDetail, setShowNodeDetail] = useState(false);
  const [showProposals, setShowProposals] = useState(false);
  const [showAccountingReview, setShowAccountingReview] = useState(false);
  const [utilityPaymentFilter, setUtilityPaymentFilter] = useState('all');
  const [utilityOverdueOnly, setUtilityOverdueOnly] = useState(false);
  const [accountingTypeFilter, setAccountingTypeFilter] = useState('all');
  const [accountingCheckFilter, setAccountingCheckFilter] = useState('all');
  const [selectedContextId, setSelectedContextId] = useState<string | null>(null);
  const [comparisonSubject, setComparisonSubject] = useState('Bonacci');
  const [selectedAccountKey, setSelectedAccountKey] = useState('');
  const [comparisonRole, setComparisonRole] = useState('actual_allocation');
  const [periodAFrom, setPeriodAFrom] = useState('2022-07-01');
  const [periodATo, setPeriodATo] = useState('2023-06-30');
  const [periodBFrom, setPeriodBFrom] = useState('2023-07-01');
  const [periodBTo, setPeriodBTo] = useState('2024-06-30');
  const [graphReviewAuthor, setGraphReviewAuthor] = useState('');
  const [graphReviewNotes, setGraphReviewNotes] = useState<Record<string, string>>({});
  const deferredSearch = useDeferredValue(searchInput.trim());
  const deferredComparisonSubject = useDeferredValue(comparisonSubject.trim());

  const topicsQuery = useKnowledgeTopics(includeInactive);
  const topics = topicsQuery.data ?? [];
  const topicSearch = useKnowledgeSearch(deferredSearch, {
    includeInactive,
    topicClass: topicClassFilter,
    topicKind: topicKindFilter,
    limit: 60,
  });
  const topicDetail = useKnowledgeTopic(selectedTopicId);
  const entityQuery = useKnowledgeEntities({
    query: deferredSearch || undefined,
    entityType: entityTypeFilter,
    limit: 40,
  });
  const entities = entityQuery.data ?? [];
  const canonicalQuery = useCanonicalEntities({
    query: deferredSearch || undefined,
    entityType: entityTypeFilter,
    limit: 40,
  });
  const entityDetail = useKnowledgeEntityDetail(selectedEntityType, selectedEntityKey);
  const graphStats = useKnowledgeGraphStats();
  const nodesQuery = useKnowledgeNodes({
    query: deferredSearch || undefined,
    nodeKind: nodeKindFilter,
    limit: 60,
  });
  const nodes = nodesQuery.data ?? [];
  const nodeDetail = useKnowledgeNode(selectedNodeId);
  const assertionsQuery = useKnowledgeAssertions({
    query: deferredSearch || undefined,
    nodeId: selectedNodeId || undefined,
    limit: 80,
  });
  const utilityLens = useSpecialistUtilityBills({
    query: deferredSearch || undefined,
    paymentStatus: utilityPaymentFilter,
    overdueOnly: utilityOverdueOnly,
    limit: 40,
  });
  const accountingLens = useSpecialistAccountingStatements({
    query: deferredSearch || undefined,
    statementType: accountingTypeFilter,
    checkStatus: accountingCheckFilter,
    limit: 40,
  });
  const contextsQuery = useKnowledgeContexts({ limit: 40 });
  const contexts = contextsQuery.data ?? [];
  const accountingSubjects = useContextAccountingSubjects(selectedContextId, {
    query: deferredComparisonSubject || undefined,
    limit: 20,
  });
  const accountingComparison = useContextAccountingComparison(selectedContextId, {
    subject: deferredComparisonSubject,
    accountKey: selectedAccountKey || undefined,
    accountingRole: comparisonRole,
    periodAFrom,
    periodATo,
    periodBFrom,
    periodBTo,
  });
  const proposals = useTopicProposals();
  const graphSuggestions = useGraphConsolidationSuggestions();
  const mergeCanonicalEntity = useMergeCanonicalEntity();
  const consolidate = useRunKnowledgeConsolidation();
  const reviewGraphSuggestion = useReviewGraphConsolidationSuggestion();

  const topicClasses = useMemo(
    () => Array.from(new Set(topics.map((topic) => topic.topic_class))).sort(),
    [topics],
  );
  const topicKinds = useMemo(
    () => Array.from(new Set(topics.map((topic) => topic.topic_kind))).sort(),
    [topics],
  );
  const visibleTopics = useMemo(() => {
    const query = deferredSearch.toLowerCase();
    const matchingIds = query.length >= 2 && topicSearch.data
      ? new Set(topicSearch.data.topics.map((hit) => hit.topic.id))
      : null;
    return topics.filter((topic) => {
      if (topicClassFilter !== 'all' && topic.topic_class !== topicClassFilter) return false;
      if (topicKindFilter !== 'all' && topic.topic_kind !== topicKindFilter) return false;
      if (!query) return true;
      if (matchingIds) return matchingIds.has(topic.id);
      return topic.title.toLowerCase().includes(query) || topic.slug.toLowerCase().includes(query);
    });
  }, [deferredSearch, topicClassFilter, topicKindFilter, topicSearch.data, topics]);
  const suggestionCount =
    (graphSuggestions.data?.subject.length ?? 0) +
    (graphSuggestions.data?.document_family.length ?? 0) +
    (graphSuggestions.data?.case_or_issue.length ?? 0);

  useEffect(() => {
    if (!contexts.length) {
      setSelectedContextId(null);
      return;
    }
    if (!selectedContextId || !contexts.some((context) => context.id === selectedContextId)) {
      setSelectedContextId(contexts[0].id);
    }
  }, [contexts, selectedContextId]);

  useEffect(() => {
    if (selectedAccountKey && !(accountingSubjects.data ?? []).some((subject) => subject.account_key === selectedAccountKey)) {
      setSelectedAccountKey('');
    }
  }, [accountingSubjects.data, selectedAccountKey]);

  useEffect(() => {
    if (!nodes.length) {
      setSelectedNodeId(null);
      return;
    }
    if (!selectedNodeId || !nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(nodes[0].id);
    }
  }, [nodes, selectedNodeId]);

  useEffect(() => {
    if (!visibleTopics.length) {
      setSelectedTopicId(null);
      return;
    }
    if (!selectedTopicId || !visibleTopics.some((topic) => topic.id === selectedTopicId)) {
      setSelectedTopicId(visibleTopics[0].id);
    }
  }, [selectedTopicId, visibleTopics]);

  useEffect(() => {
    if (!entities.length) {
      setSelectedEntityKey(null);
      setSelectedEntityType(null);
      return;
    }
    if (
      !selectedEntityKey ||
      !selectedEntityType ||
      !entities.some((entity) => entity.entity_key === selectedEntityKey && entity.entity_type === selectedEntityType)
    ) {
      setSelectedEntityKey(entities[0].entity_key);
      setSelectedEntityType(entities[0].entity_type);
    }
  }, [entities, selectedEntityKey, selectedEntityType]);

  useEffect(() => {
    if (!entityDetail.data) return;
    setNewCanonicalValue(entityDetail.data.entity_key);
    setNewCanonicalDisplay(entityDetail.data.display_value);
    setCanonicalEntityId('');
  }, [entityDetail.data]);

  useEffect(() => {
    if (!showNodeDetail && !showProposals && !showAccountingReview) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowNodeDetail(false);
        setShowProposals(false);
        setShowAccountingReview(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showNodeDetail, showProposals, showAccountingReview]);

  if (topicsQuery.isLoading) {
    return <div className="h-[calc(100vh-9rem)] animate-pulse rounded-3xl border border-white/10 bg-white/5" />;
  }

  if (topicsQuery.error) {
    return (
      <div className="rounded-xl border border-rose-300/25 bg-rose-400/10 p-4 text-rose-100">
        Errore nel caricamento: {(topicsQuery.error as Error).message}
      </div>
    );
  }

  const tabClass = (current: boolean) =>
    `rounded-full border px-4 py-2 text-sm transition ${
      current
        ? 'border-cyan-300/35 bg-cyan-400/15 text-cyan-100'
        : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
    }`;

  return (
    <div className="flex h-[calc(100vh-7.75rem)] min-h-[38rem] flex-col gap-3">
      <section className="shrink-0 rounded-3xl border border-cyan-300/15 bg-slate-950/55 p-4 shadow-[0_20px_70px_rgba(8,47,73,0.28)] backdrop-blur-xl">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex min-w-[16rem] flex-1 items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-2.5">
            <span className="text-cyan-200">⌕</span>
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Cerca soggetto, documento, topic o fatto"
              className="w-full bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
            />
            {searchInput && (
              <button onClick={() => setSearchInput('')} className="text-xs text-slate-400 hover:text-white">
                Pulisci
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-indigo-300/20 bg-indigo-400/10 px-3 py-2 text-indigo-100">
              {graphStats.data?.nodes ?? 0} nodi
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-slate-200">
              {graphStats.data?.assertions ?? 0} fatti
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-slate-200">
              {topics.length} topic
            </span>
            <button onClick={() => setShowProposals(true)} className="rounded-full border border-amber-300/20 bg-amber-400/10 px-3 py-2 text-amber-100">
              {proposals.data?.length ?? 0} proposte
            </button>
          </div>
        </div>
        <nav className="mt-3 flex flex-wrap gap-2">
          {[
            { id: 'comparisons' as Panel, label: 'Confronti' },
            { id: 'facts' as Panel, label: 'Fatti' },
            { id: 'specialists' as Panel, label: 'Specialisti' },
            { id: 'topics' as Panel, label: 'Topic' },
            { id: 'entities' as Panel, label: 'Entità' },
            { id: 'reviews' as Panel, label: `Revisioni (${suggestionCount})` },
          ].map((tab) => (
            <button key={tab.id} onClick={() => setPanel(tab.id)} className={tabClass(panel === tab.id)}>
              {tab.label}
            </button>
          ))}
        </nav>
      </section>

      <section className="min-h-0 flex-1 overflow-hidden rounded-3xl border border-white/10 bg-white/5 p-4 backdrop-blur-md">
        {panel === 'comparisons' && (
          <div className="flex h-full flex-col gap-3">
            <div className="grid shrink-0 gap-2 rounded-2xl border border-white/10 bg-slate-950/35 p-3 lg:grid-cols-[minmax(14rem,2fr)_minmax(10rem,1fr)_minmax(10rem,1fr)_minmax(10rem,1fr)]">
              <select
                value={selectedContextId ?? ''}
                onChange={(event) => setSelectedContextId(event.target.value || null)}
                className="rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm"
              >
                {contexts.length === 0 && <option value="">Nessun contesto disponibile</option>}
                {contexts.map((context) => (
                  <option key={context.id} value={context.id}>{context.label}</option>
                ))}
              </select>
              <input
                value={comparisonSubject}
                onChange={(event) => { setComparisonSubject(event.target.value); setSelectedAccountKey(''); }}
                placeholder="Soggetto, es. Bonacci"
                className="rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm"
              />
              <select
                value={selectedAccountKey}
                onChange={(event) => setSelectedAccountKey(event.target.value)}
                className="rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm"
              >
                <option value="">Risoluzione automatica</option>
                {(accountingSubjects.data ?? []).map((subject) => (
                  <option key={subject.account_key} value={subject.account_key}>
                    {subject.subject_label} {subject.unit_codes.join(' / ')}
                  </option>
                ))}
              </select>
              <select
                value={comparisonRole}
                onChange={(event) => setComparisonRole(event.target.value)}
                className="rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm"
              >
                <option value="actual_allocation">Consuntivo spese</option>
                <option value="budget_allocation">Preventivo spese</option>
              </select>
            </div>
            <div className="grid shrink-0 gap-2 rounded-2xl border border-white/10 bg-slate-950/35 p-3 md:grid-cols-2">
              <div className="flex items-center gap-2">
                <span className="text-xs uppercase tracking-wide text-slate-400">Periodo A</span>
                <input type="date" value={periodAFrom} onChange={(event) => setPeriodAFrom(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-white/10 bg-slate-950 px-2 py-2 text-sm" />
                <input type="date" value={periodATo} onChange={(event) => setPeriodATo(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-white/10 bg-slate-950 px-2 py-2 text-sm" />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs uppercase tracking-wide text-slate-400">Periodo B</span>
                <input type="date" value={periodBFrom} onChange={(event) => setPeriodBFrom(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-white/10 bg-slate-950 px-2 py-2 text-sm" />
                <input type="date" value={periodBTo} onChange={(event) => setPeriodBTo(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-white/10 bg-slate-950 px-2 py-2 text-sm" />
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-4">
              {accountingComparison.isLoading ? (
                <p className="text-sm text-slate-400">Elaborazione confronto...</p>
              ) : accountingComparison.data ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-lg font-semibold text-white">
                        {accountingComparison.data.selected_subject?.subject_label ?? comparisonSubject}
                      </p>
                      <p className="mt-1 text-sm text-slate-400">
                        {contexts.find((context) => context.id === selectedContextId)?.label ?? 'Contesto'} · {comparisonRole}
                      </p>
                    </div>
                    <span className={`rounded-full border px-3 py-2 text-xs ${
                      accountingComparison.data.status === 'comparable'
                        ? 'border-emerald-300/25 bg-emerald-400/15 text-emerald-100'
                        : accountingComparison.data.status === 'needs_review'
                          ? 'border-amber-300/25 bg-amber-400/15 text-amber-100'
                          : 'border-slate-300/20 bg-white/5 text-slate-200'
                    }`}>
                      {accountingComparison.data.status}
                    </span>
                  </div>
                  {accountingComparison.data.status === 'comparable' && (
                    <div className="grid gap-3 md:grid-cols-3">
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs text-slate-400">Periodo A</p>
                        <p className="mt-1 text-lg text-white">{formatCurrency(accountingComparison.data.period_a?.total)}</p>
                      </div>
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs text-slate-400">Periodo B</p>
                        <p className="mt-1 text-lg text-white">{formatCurrency(accountingComparison.data.period_b?.total)}</p>
                      </div>
                      <div className="rounded-xl border border-cyan-300/20 bg-cyan-400/10 p-3">
                        <p className="text-xs text-cyan-100">Differenza B - A</p>
                        <p className="mt-1 text-lg text-white">{formatCurrency(accountingComparison.data.delta)}</p>
                        <p className="text-xs text-slate-300">{accountingComparison.data.percentage_change}%</p>
                      </div>
                    </div>
                  )}
                  {accountingComparison.data.warnings.map((warning) => (
                    <p key={warning} className="rounded-xl border border-amber-300/20 bg-amber-400/10 p-3 text-sm text-amber-100">{warning}</p>
                  ))}
                  {accountingComparison.data.status === 'needs_review' && (
                    <button
                      onClick={() => setShowAccountingReview(true)}
                      className="rounded-full border border-amber-300/25 bg-amber-400/15 px-4 py-2 text-sm text-amber-100"
                    >
                      Riconcilia tabella
                    </button>
                  )}
                  {accountingComparison.data.selected_subject && (
                    <p className="text-xs text-slate-400">
                      Periodi disponibili: {accountingComparison.data.selected_subject.available_periods.map((period) => `${period.accounting_role} ${formatDate(period.period_from)}-${formatDate(period.period_to)}`).join(' · ')}
                    </p>
                  )}
                  {accountingComparison.data.changed_categories.length > 0 && (
                    <div className="overflow-hidden rounded-xl border border-white/10">
                      <div className="grid grid-cols-[minmax(12rem,1fr)_8rem_8rem_8rem] bg-white/5 px-3 py-2 text-xs uppercase tracking-wide text-slate-400">
                        <span>Voce</span><span className="text-right">A</span><span className="text-right">B</span><span className="text-right">Delta</span>
                      </div>
                      {accountingComparison.data.changed_categories.map((category) => (
                        <div key={category.category_key} className="grid grid-cols-[minmax(12rem,1fr)_8rem_8rem_8rem] border-t border-white/10 px-3 py-2 text-sm">
                          <span className="truncate text-white">{category.category_label}</span>
                          <span className="text-right text-slate-300">{formatCurrency(category.amount_a)}</span>
                          <span className="text-right text-slate-300">{formatCurrency(category.amount_b)}</span>
                          <span className="text-right text-cyan-100">{formatCurrency(category.delta)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-slate-400">Seleziona un contesto e indica un soggetto da confrontare.</p>
              )}
            </div>
          </div>
        )}

        {panel === 'facts' && (
          <div className="flex h-full flex-col gap-3">
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                {[
                  ['all', 'Tutti'],
                  ['organization', 'Organizzazioni'],
                  ['address', 'Indirizzi'],
                  ['person', 'Persone'],
                  ['place', 'Luoghi'],
                ].map(([value, label]) => (
                  <button key={value} onClick={() => setNodeKindFilter(value)} className={tabClass(nodeKindFilter === value)}>
                    {label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setShowNodeDetail(true)}
                disabled={!selectedNodeId}
                className="rounded-full border border-indigo-300/25 bg-indigo-400/15 px-4 py-2 text-sm text-indigo-100 disabled:opacity-40"
              >
                Dettaglio e fonti
              </button>
            </div>
            <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[0.9fr_1.1fr]">
              <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-3">
                {nodesQuery.isLoading ? (
                  <p className="text-sm text-slate-400">Caricamento nodi...</p>
                ) : nodes.length === 0 ? (
                  <p className="text-sm text-slate-400">Nessun nodo trovato.</p>
                ) : (
                  <div className="space-y-2">
                    {nodes.map((node) => (
                      <button
                        key={node.id}
                        onClick={() => setSelectedNodeId(node.id)}
                        className={`w-full rounded-xl border p-3 text-left ${
                          node.id === selectedNodeId ? 'border-indigo-300/35 bg-indigo-400/15' : 'border-white/10 bg-white/5 hover:bg-white/10'
                        }`}
                      >
                        <p className="truncate text-sm font-medium text-white">{node.label}</p>
                        <p className="mt-1 text-xs text-slate-400">
                          {node.node_kind} · {node.document_count} documenti · {node.alias_count} alias
                        </p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="min-h-0 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-3">
                {assertionsQuery.isLoading ? (
                  <p className="text-sm text-slate-400">Caricamento fatti...</p>
                ) : assertionsQuery.data?.length ? (
                  <div className="grid gap-2 md:grid-cols-2">
                    {assertionsQuery.data.map((assertion) => (
                      <article key={assertion.id} className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <div className="flex justify-between gap-2 text-xs">
                          <span className="uppercase tracking-wide text-indigo-200">{assertion.predicate_label}</span>
                          <span className="text-slate-500">{assertion.source_type}</span>
                        </div>
                        <p className="mt-2 text-sm text-white">{formatAssertionValue(assertion)}</p>
                        {assertion.confidence !== null && (
                          <p className="mt-1 text-xs text-slate-400">{Math.round(assertion.confidence * 100)}% confidenza</p>
                        )}
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">Nessun fatto collegato.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {panel === 'specialists' && (
          <div className="flex h-full flex-col gap-3">
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <button onClick={() => setSpecialistPanel('accounting')} className={tabClass(specialistPanel === 'accounting')}>
                Rendiconti ({accountingLens.data?.total ?? 0})
              </button>
              <button onClick={() => setSpecialistPanel('utility')} className={tabClass(specialistPanel === 'utility')}>
                Bollette ({utilityLens.data?.total ?? 0})
              </button>
              {specialistPanel === 'accounting' ? (
                <>
                  <select value={accountingTypeFilter} onChange={(event) => setAccountingTypeFilter(event.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
                    <option value="all">Tutti i tipi</option>
                    <option value="rendiconto_composito">Rendiconto composito</option>
                    <option value="bilancio_preventivo">Bilancio preventivo</option>
                    <option value="riparto_spese">Riparto spese</option>
                    <option value="rendiconto">Rendiconto</option>
                    <option value="estratto_contabile">Estratto contabile</option>
                  </select>
                  <select value={accountingCheckFilter} onChange={(event) => setAccountingCheckFilter(event.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
                    <option value="all">Tutti i check</option>
                    <option value="pass">Passati</option>
                    <option value="fail">Falliti</option>
                    <option value="unknown">Ignoto</option>
                  </select>
                </>
              ) : (
                <>
                  <select value={utilityPaymentFilter} onChange={(event) => setUtilityPaymentFilter(event.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
                    <option value="all">Tutti i pagamenti</option>
                    <option value="paid">Pagate</option>
                    <option value="unpaid">Non pagate</option>
                    <option value="unknown">Ignoto</option>
                  </select>
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input type="checkbox" checked={utilityOverdueOnly} onChange={(event) => setUtilityOverdueOnly(event.target.checked)} />
                    Scadute
                  </label>
                </>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/35 p-3">
              {specialistPanel === 'accounting' ? (
                accountingLens.isLoading ? (
                  <p className="text-sm text-slate-400">Caricamento rendiconti...</p>
                ) : accountingLens.data?.items.length ? (
                  <div className="grid gap-3 xl:grid-cols-2">
                    {accountingLens.data.items.map((statement) => (
                      <article key={statement.result_id} className="rounded-xl border border-white/10 bg-white/5 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-medium text-white">{statement.statement_type ?? 'Rendiconto'}</p>
                            <p className="mt-1 truncate text-xs text-slate-400">{statement.original_filename}</p>
                          </div>
                          <span className={statement.has_failed_checks ? 'text-xs text-rose-200' : 'text-xs text-emerald-200'}>
                            {statement.has_failed_checks ? 'da verificare' : 'coerente'}
                          </span>
                        </div>
                        <p className="mt-3 line-clamp-2 text-sm text-slate-300">{statement.summary ?? 'Nessun riassunto.'}</p>
                        <p className="mt-3 text-xs text-slate-300">
                          {formatDate(statement.accounting_period_from)} - {formatDate(statement.accounting_period_to)} · {statement.section_count} sezioni · {statement.table_count} tabelle
                        </p>
                        {statement.sections.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {statement.sections.slice(0, 6).map((section) => (
                              <span key={String(section.section_id)} className="rounded-full border border-white/10 bg-slate-950/50 px-2 py-1 text-xs text-slate-300">
                                {String(section.label || 'Sezione')} · {String(section.table_count || 0)}
                              </span>
                            ))}
                            {statement.sections.length > 6 && (
                              <span className="rounded-full border border-white/10 bg-slate-950/50 px-2 py-1 text-xs text-slate-400">
                                +{statement.sections.length - 6}
                              </span>
                            )}
                          </div>
                        )}
                        <div className="mt-3 flex gap-2">
                          {statement.document_id && (
                            <button onClick={() => onOpenDocument(statement.document_id!)} className={tabClass(false)}>Documento</button>
                          )}
                          <a href={`/api/knowledge/specialist-results/${statement.result_id}/export?format=json`} target="_blank" rel="noreferrer" className={tabClass(false)}>JSON</a>
                          <a href={`/api/knowledge/specialist-results/${statement.result_id}/export?format=csv`} className={tabClass(false)}>CSV</a>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">Nessun rendiconto trovato.</p>
                )
              ) : utilityLens.isLoading ? (
                <p className="text-sm text-slate-400">Caricamento bollette...</p>
              ) : utilityLens.data?.items.length ? (
                <div className="grid gap-3 xl:grid-cols-2">
                  {utilityLens.data.items.map((bill) => (
                    <article key={bill.result_id} className="rounded-xl border border-white/10 bg-white/5 p-4">
                      <div className="flex justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-medium text-white">{bill.issuer ?? 'Emittente non disponibile'}</p>
                          <p className="mt-1 truncate text-xs text-slate-400">{bill.original_filename}</p>
                        </div>
                        <p className="font-medium text-white">{formatCurrency(bill.total_amount)}</p>
                      </div>
                      <p className="mt-3 text-sm text-slate-300">
                        Scadenza {formatDate(bill.due_date)} · {bill.payment_status ?? 'unknown'}
                      </p>
                      <div className="mt-3 flex gap-2">
                        {bill.document_id && <button onClick={() => onOpenDocument(bill.document_id!)} className={tabClass(false)}>Documento</button>}
                        <a href={`/api/knowledge/specialist-results/${bill.result_id}/export?format=json`} target="_blank" rel="noreferrer" className={tabClass(false)}>JSON</a>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-400">Nessuna bolletta valida trovata.</p>
              )}
            </div>
          </div>
        )}

        {panel === 'topics' && (
          <div className="flex h-full flex-col gap-3">
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" checked={includeInactive} onChange={(event) => setIncludeInactive(event.target.checked)} />
                Inattivi
              </label>
              <select value={topicClassFilter} onChange={(event) => setTopicClassFilter(event.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
                <option value="all">Tutte le classi</option>
                {topicClasses.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
              <select value={topicKindFilter} onChange={(event) => setTopicKindFilter(event.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
                <option value="all">Tutti i tipi</option>
                {topicKinds.map((value) => <option key={value} value={value}>{value}</option>)}
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
                {topicDetail.isLoading ? (
                  <p className="text-sm text-slate-400">Caricamento...</p>
                ) : topicDetail.data ? (
                  <div>
                    <p className="text-lg font-semibold text-white">{topicDetail.data.topic.title}</p>
                    <p className="mt-1 text-sm text-slate-400">
                      {topicDetail.data.topic.topic_kind} · {topicDetail.data.topic.topic_class} · {topicDetail.data.related_documents.length} documenti
                    </p>
                    {topicDetail.data.topic.description && <p className="mt-3 text-sm text-slate-300">{topicDetail.data.topic.description}</p>}
                    <div className="mt-4 grid gap-2 xl:grid-cols-2">
                      {topicDetail.data.related_documents.map((document) => (
                        <button key={document.document_unit_id} onClick={() => onOpenDocument(document.document_id)} className="rounded-xl border border-white/10 bg-white/5 p-3 text-left hover:bg-white/10">
                          <p className="truncate text-sm text-cyan-200">{document.original_filename}</p>
                          <p className="mt-1 text-xs text-slate-400">Pagine {document.start_page}-{document.end_page}</p>
                          {document.summary && <p className="mt-2 line-clamp-2 text-xs text-slate-300">{document.summary}</p>}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">Seleziona un topic.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {panel === 'entities' && (
          <div className="flex h-full flex-col gap-3">
            <div className="shrink-0">
              <select value={entityTypeFilter} onChange={(event) => setEntityTypeFilter(event.target.value)} className="rounded-full border border-white/10 bg-slate-950 px-3 py-2 text-sm">
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
                        <select value={canonicalEntityId} onChange={(event) => setCanonicalEntityId(event.target.value)} className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm">
                          <option value="">Nuova entità canonica</option>
                          {(canonicalQuery.data ?? []).filter((item) => item.entity_type === entityDetail.data?.entity_type).map((item) => (
                            <option key={item.id} value={item.id}>{item.display_value}</option>
                          ))}
                        </select>
                        {!canonicalEntityId && <input value={newCanonicalDisplay} onChange={(event) => setNewCanonicalDisplay(event.target.value)} className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm" />}
                        {!canonicalEntityId && <input value={newCanonicalValue} onChange={(event) => setNewCanonicalValue(event.target.value)} className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm md:col-span-2" />}
                      </div>
                      <button
                        onClick={() => mergeCanonicalEntity.mutate({
                          entity_type: entityDetail.data!.entity_type,
                          entity_keys: [entityDetail.data!.entity_key],
                          target_canonical_entity_id: canonicalEntityId || undefined,
                          create_canonical_entity: canonicalEntityId ? undefined : {
                            entity_type: entityDetail.data!.entity_type,
                            canonical_value: newCanonicalValue || entityDetail.data!.entity_key,
                            display_value: newCanonicalDisplay || entityDetail.data!.display_value,
                          },
                        })}
                        className="mt-3 rounded-full border border-violet-300/25 bg-violet-400/20 px-4 py-2 text-sm text-violet-50"
                      >
                        Salva canonizzazione
                      </button>
                    </div>
                    <div className="grid gap-2 xl:grid-cols-2">
                      {entityDetail.data.documents.map((document) => (
                        <button key={document.document_unit_id} onClick={() => onOpenDocument(document.document_id)} className="rounded-xl border border-white/10 bg-white/5 p-3 text-left">
                          <p className="truncate text-sm text-cyan-200">{document.original_filename}</p>
                          <p className="mt-1 text-xs text-slate-400">Pagine {document.start_page}-{document.end_page}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : <p className="text-sm text-slate-400">Seleziona un’entità.</p>}
              </div>
            </div>
          </div>
        )}

        {panel === 'reviews' && (
          <div className="flex h-full flex-col gap-3">
            <input value={graphReviewAuthor} onChange={(event) => setGraphReviewAuthor(event.target.value)} placeholder="Revisore (facoltativo)" className="shrink-0 rounded-xl border border-white/10 bg-slate-950/50 px-3 py-2 text-sm" />
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
                          <textarea value={graphReviewNotes[key] ?? ''} onChange={(event) => setGraphReviewNotes((value) => ({ ...value, [key]: event.target.value }))} placeholder="Nota" className="mt-3 h-16 w-full rounded-lg border border-white/10 bg-slate-950/60 p-2 text-xs" />
                          <div className="mt-2 flex flex-wrap gap-2">
                            {[
                              ['merge_into_target', 'Unisci', 'border-emerald-300/25 text-emerald-100'],
                              ['dismiss', 'Ignora', 'border-white/10 text-slate-200'],
                              ['mark_same_subject_different_family', 'Separa', 'border-amber-300/25 text-amber-100'],
                              ['convert_to_secondary_relationship', 'Secondaria', 'border-fuchsia-300/25 text-fuchsia-100'],
                            ].map(([action, label, colors]) => (
                              <button
                                key={action}
                                onClick={() => reviewGraphSuggestion.mutate({
                                  axis: group.axis as 'subject' | 'document_family' | 'case_or_issue',
                                  source_topic_id: item.source_topic.id,
                                  target_topic_id: item.target_topic.id,
                                  action: action as 'merge_into_target' | 'dismiss' | 'mark_same_subject_different_family' | 'convert_to_secondary_relationship',
                                  note: graphReviewNotes[key] || null,
                                  acted_by: graphReviewAuthor || null,
                                })}
                                className={`rounded-full border px-3 py-1.5 text-xs ${colors}`}
                              >
                                {label}
                              </button>
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
        )}
      </section>

      {showNodeDetail && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-sm" onClick={() => setShowNodeDetail(false)}>
          <div className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-3xl border border-indigo-300/20 bg-slate-900 p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-lg font-semibold text-white">{nodeDetail.data?.node.label ?? 'Dettaglio nodo'}</p>
              <button onClick={() => setShowNodeDetail(false)} className={tabClass(false)}>Chiudi</button>
            </div>
            <div className="min-h-0 overflow-y-auto">
              {nodeDetail.data && (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    {nodeDetail.data.aliases.map((alias) => <span key={alias} className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">{alias}</span>)}
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    {nodeDetail.data.documents.map((document) => (
                      <button key={document.document_unit_id} onClick={() => onOpenDocument(document.document_id)} className="rounded-xl border border-white/10 bg-white/5 p-3 text-left hover:bg-white/10">
                        <p className="truncate text-sm text-cyan-200">{document.original_filename}</p>
                        <p className="mt-1 text-xs text-slate-400">Pagine {document.start_page}-{document.end_page}</p>
                        {document.summary && <p className="mt-2 line-clamp-2 text-xs text-slate-300">{document.summary}</p>}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {showProposals && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-sm" onClick={() => setShowProposals(false)}>
          <div className="max-h-[88vh] w-full max-w-5xl overflow-y-auto rounded-3xl border border-amber-300/20 bg-slate-900 p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <ProposalList
              initialProposals={proposals.data}
              onClose={() => setShowProposals(false)}
            />
          </div>
        </div>
      )}

      {showAccountingReview && accountingComparison.data && (
        <AccountingReconciliationModal
          comparison={accountingComparison.data}
          onClose={() => setShowAccountingReview(false)}
        />
      )}
    </div>
  );
}

export default KnowledgeBase;
