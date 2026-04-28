import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  useKnowledgeEntities,
  useKnowledgeEntityDetail,
  useKnowledgeSearch,
  useKnowledgeTopic,
  useKnowledgeTopics,
  useRunKnowledgeConsolidation,
  useTopicProposals,
} from '../hooks/useDocuments';
import ProposalList from './ProposalList';

interface Props {
  onOpenDocument: (documentId: string) => void;
}

function KnowledgeBase({ onOpenDocument }: Props) {
  const [includeInactive, setIncludeInactive] = useState(false);
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const [topicClassFilter, setTopicClassFilter] = useState<string>('all');
  const [topicKindFilter, setTopicKindFilter] = useState<string>('all');
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('all');
  const [selectedEntityKey, setSelectedEntityKey] = useState<string | null>(null);
  const [selectedEntityType, setSelectedEntityType] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [showProposals, setShowProposals] = useState(false);
  const deferredSearch = useDeferredValue(searchInput.trim());

  const { data: topics, isLoading, error } = useKnowledgeTopics(includeInactive);
  const { data: topicDetail, isLoading: topicLoading, error: topicError } = useKnowledgeTopic(selectedTopicId);
  const { data: entityMatches = [], isLoading: entitiesLoading } = useKnowledgeEntities({
    query: deferredSearch || undefined,
    entityType: entityTypeFilter,
    limit: 14,
  });
  const { data: entityDetail, isLoading: entityDetailLoading } = useKnowledgeEntityDetail(
    selectedEntityType,
    selectedEntityKey,
  );
  const { data: proposals } = useTopicProposals();
  const search = useKnowledgeSearch(deferredSearch, {
    includeInactive,
    topicClass: topicClassFilter,
    topicKind: topicKindFilter,
    limit: 14,
  });
  const consolidate = useRunKnowledgeConsolidation();

  const topicClasses = useMemo(() => {
    return Array.from(new Set((topics ?? []).map((topic) => topic.topic_class))).sort();
  }, [topics]);

  const topicKinds = useMemo(() => {
    return Array.from(new Set((topics ?? []).map((topic) => topic.topic_kind))).sort();
  }, [topics]);

  const visibleTopics = useMemo(() => {
    if (!topics) {
      return [];
    }
    const filtered = topics.filter((topic) => {
      const classOk = topicClassFilter === 'all' || topic.topic_class === topicClassFilter;
      const kindOk = topicKindFilter === 'all' || topic.topic_kind === topicKindFilter;
      return classOk && kindOk;
    });

    if (deferredSearch.length >= 2 && search.data) {
      const topicIds = new Set(search.data.topics.map((hit) => hit.topic.id));
      return filtered.filter((topic) => topicIds.has(topic.id));
    }

    return filtered;
  }, [deferredSearch.length, search.data, topicClassFilter, topicKindFilter, topics]);

  const stats = useMemo(() => {
    const source = topics ?? [];
    return {
      totalTopics: source.length,
      totalAssignments: source.reduce((acc, topic) => acc + topic.assignment_count, 0),
      totalAliases: source.reduce((acc, topic) => acc + topic.alias_count, 0),
      topicClasses: topicClasses.length,
    };
  }, [topicClasses.length, topics]);

  const searchActive = deferredSearch.length >= 2;
  const searchTopicHits = search.data?.topics ?? [];
  const searchDocumentHits = search.data?.document_units ?? [];
  const entityTypes = useMemo(() => {
    return Array.from(new Set(entityMatches.map((entity) => entity.entity_type))).sort();
  }, [entityMatches]);

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
    if (!entityMatches.length) {
      setSelectedEntityKey(null);
      setSelectedEntityType(null);
      return;
    }
    if (
      !selectedEntityKey ||
      !selectedEntityType ||
      !entityMatches.some((entity) => entity.entity_key === selectedEntityKey && entity.entity_type === selectedEntityType)
    ) {
      setSelectedEntityKey(entityMatches[0].entity_key);
      setSelectedEntityType(entityMatches[0].entity_type);
    }
  }, [entityMatches, selectedEntityKey, selectedEntityType]);

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-1/3"></div>
        <div className="grid gap-4 lg:grid-cols-[24rem_minmax(0,1fr)]">
          <div className="h-[32rem] bg-gray-200 rounded"></div>
          <div className="h-[32rem] bg-gray-200 rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-lg">
        Error loading knowledge base: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-[32px] border border-cyan-300/15 bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.18),_transparent_36%),radial-gradient(circle_at_bottom_right,_rgba(56,189,248,0.12),_transparent_28%),rgba(2,6,23,0.82)] backdrop-blur-2xl shadow-[0_30px_120px_rgba(8,47,73,0.45)] overflow-hidden">
        <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr] p-6 lg:p-8">
          <div className="space-y-5">
            <div>
              <p className="text-xs uppercase tracking-[0.35em] text-cyan-300/75 mb-3">Knowledge Atlas</p>
              <h2 className="text-3xl lg:text-4xl font-semibold text-white">Search the corpus like a living graph</h2>
              <p className="text-sm text-slate-300 mt-3 max-w-2xl">
                Find topics, aliases and document fragments from the same console used to consolidate the knowledge base.
              </p>
            </div>

            <div className="rounded-[24px] border border-cyan-300/20 bg-slate-950/65 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
              <div className="flex items-center gap-3 rounded-[20px] border border-white/10 bg-white/5 px-4 py-3">
                <span className="text-cyan-200 text-lg">⌕</span>
                <input
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                  placeholder="Search by topic, alias, vendor, filename, issue, address..."
                  className="w-full bg-transparent text-sm text-white placeholder:text-slate-500 outline-none"
                />
                {searchInput && (
                  <button
                    onClick={() => setSearchInput('')}
                    className="rounded-full border border-white/10 px-2 py-1 text-xs text-slate-300 hover:bg-white/10"
                  >
                    Clear
                  </button>
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">topics</span>
                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">document units</span>
                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">entities</span>
                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">aliases</span>
                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1">summaries</span>
                {search.isFetching && searchActive && (
                  <span className="rounded-full border border-cyan-400/25 bg-cyan-400/10 px-2 py-1 text-cyan-100">
                    searching...
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-cyan-300/15 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-wide text-cyan-200/70">Topics</p>
              <p className="mt-2 text-2xl font-semibold text-white">{stats.totalTopics}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-wide text-cyan-200/70">Assignments</p>
              <p className="mt-2 text-2xl font-semibold text-white">{stats.totalAssignments}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-wide text-cyan-200/70">Aliases</p>
              <p className="mt-2 text-2xl font-semibold text-white">{stats.totalAliases}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-wide text-cyan-200/70">Classes</p>
              <p className="mt-2 text-2xl font-semibold text-white">{stats.topicClasses}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Explore and refine</h3>
          <p className="text-sm text-slate-400">
            Search first, then jump into the right topic or document unit to consolidate.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-slate-300 flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(event) => setIncludeInactive(event.target.checked)}
              className="rounded border-white/20 bg-slate-900 text-cyan-400 focus:ring-cyan-400"
            />
            Show inactive
          </label>
          <select
            value={topicClassFilter}
            onChange={(event) => setTopicClassFilter(event.target.value)}
            className="rounded-full border border-white/10 bg-slate-900/70 px-4 py-2 text-sm text-slate-100"
          >
            <option value="all">All classes</option>
            {topicClasses.map((topicClass) => (
              <option key={topicClass} value={topicClass}>
                {topicClass}
              </option>
            ))}
          </select>
          <select
            value={topicKindFilter}
            onChange={(event) => setTopicKindFilter(event.target.value)}
            className="rounded-full border border-white/10 bg-slate-900/70 px-4 py-2 text-sm text-slate-100"
          >
            <option value="all">All kinds</option>
            {topicKinds.map((topicKind) => (
              <option key={topicKind} value={topicKind}>
                {topicKind}
              </option>
            ))}
          </select>
          <select
            value={entityTypeFilter}
            onChange={(event) => setEntityTypeFilter(event.target.value)}
            className="rounded-full border border-white/10 bg-slate-900/70 px-4 py-2 text-sm text-slate-100"
          >
            <option value="all">All entity types</option>
            {entityTypes.map((entityType) => (
              <option key={entityType} value={entityType}>
                {entityType}
              </option>
            ))}
          </select>
          <button
            onClick={() => setShowProposals(true)}
            className="px-4 py-2 rounded-full bg-amber-400/15 text-amber-200 text-sm font-medium border border-amber-300/25 hover:bg-amber-400/20 flex items-center gap-2"
          >
            Pending proposals
            {proposals && proposals.length > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-amber-400/25 text-amber-100 text-xs">
                {proposals.length}
              </span>
            )}
          </button>
          <button
            onClick={() => consolidate.mutate()}
            disabled={consolidate.isPending}
            className="px-4 py-2 rounded-full bg-cyan-400/15 text-cyan-200 text-sm font-medium border border-cyan-300/25 hover:bg-cyan-400/20 disabled:opacity-60"
          >
            {consolidate.isPending ? 'Consolidating...' : 'Run Consolidation'}
          </button>
        </div>
      </div>

      {consolidate.data && (
        <div className="rounded-2xl border border-emerald-400/25 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
          Topics {consolidate.data.topics_before} → {consolidate.data.topics_after}, merged{' '}
          {consolidate.data.topics_merged}, retargeted assignments {consolidate.data.assignments_retargeted}, aliases{' '}
          {consolidate.data.aliases_created}.
        </div>
      )}

      {searchActive && (
        <div className="grid gap-4 xl:grid-cols-[0.95fr_0.95fr_1.1fr]">
          <div className="rounded-[24px] border border-cyan-300/15 bg-slate-950/50 p-5 shadow-[0_18px_60px_rgba(2,6,23,0.35)] backdrop-blur-md">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-cyan-300/70">Search Topics</p>
                <h4 className="text-lg font-semibold text-white">Topic matches</h4>
              </div>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200">
                {search.data?.total_topic_hits ?? 0} hits
              </span>
            </div>

            {search.isLoading ? (
              <div className="space-y-3 animate-pulse">
                <div className="h-16 rounded-2xl bg-white/5"></div>
                <div className="h-16 rounded-2xl bg-white/5"></div>
              </div>
            ) : searchTopicHits.length === 0 ? (
              <p className="text-sm text-slate-400">No topics matched this query.</p>
            ) : (
              <div className="space-y-3">
                {searchTopicHits.map((hit) => (
                  <button
                    key={hit.topic.id}
                    onClick={() => setSelectedTopicId(hit.topic.id)}
                    className="w-full rounded-2xl border border-white/10 bg-white/5 p-4 text-left hover:bg-cyan-400/10 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-medium text-slate-100 truncate">{hit.topic.title}</p>
                        <p className="text-xs text-slate-400 mt-1">
                          {hit.topic.topic_kind} · {hit.topic.topic_class} · {hit.topic.assignment_count} assignments
                        </p>
                      </div>
                      <span className="rounded-full border border-cyan-300/20 bg-cyan-400/10 px-2 py-1 text-[11px] uppercase tracking-[0.18em] text-cyan-100">
                        inspect
                      </span>
                    </div>
                    {(hit.aliases.length > 0 || hit.matched_fields.length > 0) && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {hit.matched_fields.map((field) => (
                          <span key={field} className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-slate-300">
                            {field}
                          </span>
                        ))}
                        {hit.aliases.slice(0, 3).map((alias) => (
                          <span key={alias} className="rounded-full border border-white/10 bg-slate-900/60 px-2 py-1 text-[11px] text-slate-300">
                            {alias}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-[24px] border border-white/10 bg-slate-950/50 p-5 shadow-[0_18px_60px_rgba(2,6,23,0.35)] backdrop-blur-md">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-cyan-300/70">Search Documents</p>
                <h4 className="text-lg font-semibold text-white">Document-unit matches</h4>
              </div>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200">
                {search.data?.total_document_hits ?? 0} hits
              </span>
            </div>

            {search.isLoading ? (
              <div className="space-y-3 animate-pulse">
                <div className="h-20 rounded-2xl bg-white/5"></div>
                <div className="h-20 rounded-2xl bg-white/5"></div>
              </div>
            ) : searchDocumentHits.length === 0 ? (
              <p className="text-sm text-slate-400">No document units matched this query.</p>
            ) : (
              <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
                {searchDocumentHits.map((hit) => (
                  <div key={hit.document_unit_id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <button
                          onClick={() => onOpenDocument(hit.document_id)}
                          className="text-left font-medium text-cyan-200 hover:text-cyan-100"
                        >
                          {hit.original_filename}
                        </button>
                        <p className="text-xs text-slate-400 mt-1">
                          Pages {hit.start_page}-{hit.end_page}
                          {hit.document_type_code ? ` · ${hit.document_type_code}` : ''}
                          {hit.external_id ? ` · ${hit.external_id}` : ''}
                        </p>
                        {hit.title && <p className="text-sm text-slate-200 mt-3">{hit.title}</p>}
                        {hit.summary && <p className="text-sm text-slate-400 mt-2 line-clamp-3">{hit.summary}</p>}
                      </div>
                      <span className="rounded-full border border-white/10 bg-slate-900/70 px-2 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-200">
                        {hit.review_status}
                      </span>
                    </div>

                    {(hit.topic_titles.length > 0 || hit.matched_fields.length > 0) && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {hit.matched_fields.map((field) => (
                          <span key={field} className="rounded-full border border-cyan-300/20 bg-cyan-400/10 px-2 py-1 text-[11px] text-cyan-100">
                            {field}
                          </span>
                        ))}
                        {hit.topic_titles.slice(0, 3).map((topicTitle, index) => (
                          <button
                            key={`${hit.document_unit_id}-${topicTitle}-${index}`}
                            onClick={() => {
                              const matchedHit = searchTopicHits.find((item) => item.topic.title === topicTitle);
                              if (matchedHit) {
                                setSelectedTopicId(matchedHit.topic.id);
                              }
                            }}
                            className="rounded-full border border-white/10 bg-slate-900/60 px-2 py-1 text-[11px] text-slate-300 hover:bg-white/10"
                          >
                            {topicTitle}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-[24px] border border-violet-300/15 bg-slate-950/50 p-5 shadow-[0_18px_60px_rgba(2,6,23,0.35)] backdrop-blur-md">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-violet-300/70">Entity Index</p>
                <h4 className="text-lg font-semibold text-white">Canonicalized entity matches</h4>
              </div>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200">
                {entityMatches.length} hits
              </span>
            </div>

            <div className="grid gap-4 xl:grid-cols-[0.92fr_1.08fr]">
              <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
                {entitiesLoading ? (
                  <div className="space-y-3 animate-pulse">
                    <div className="h-16 rounded-2xl bg-white/5"></div>
                    <div className="h-16 rounded-2xl bg-white/5"></div>
                  </div>
                ) : entityMatches.length === 0 ? (
                  <p className="text-sm text-slate-400">No entities matched this query.</p>
                ) : (
                  entityMatches.map((entity) => (
                    <button
                      key={`${entity.entity_type}:${entity.entity_key}`}
                      onClick={() => {
                        setSelectedEntityType(entity.entity_type);
                        setSelectedEntityKey(entity.entity_key);
                      }}
                      className={`w-full rounded-2xl border p-4 text-left transition-colors ${
                        entity.entity_type === selectedEntityType && entity.entity_key === selectedEntityKey
                          ? 'border-violet-300/35 bg-violet-400/10'
                          : 'border-white/10 bg-white/5 hover:bg-white/10'
                      }`}
                    >
                      <p className="font-medium text-slate-100">{entity.display_value}</p>
                      <p className="text-xs text-slate-400 mt-1">
                        {entity.entity_type} · {entity.document_count} documents · {entity.mention_count} mentions · {entity.topic_count}{' '}
                        topics
                      </p>
                    </button>
                  ))
                )}
              </div>

              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 min-h-[16rem]">
                {!selectedEntityKey || !selectedEntityType ? (
                  <p className="text-sm text-slate-400">Select an entity to inspect its linked documents.</p>
                ) : entityDetailLoading ? (
                  <div className="space-y-3 animate-pulse">
                    <div className="h-6 rounded bg-white/5 w-2/3"></div>
                    <div className="h-24 rounded bg-white/5"></div>
                  </div>
                ) : entityDetail ? (
                  <div className="space-y-4">
                    <div>
                      <p className="text-lg font-semibold text-white">{entityDetail.display_value}</p>
                      <p className="text-sm text-slate-400">
                        {entityDetail.entity_type} · {entityDetail.document_count} documents · {entityDetail.mention_count} mentions
                      </p>
                    </div>
                    <div className="space-y-3 max-h-[23rem] overflow-y-auto pr-1">
                      {entityDetail.documents.map((document) => (
                        <div key={document.document_unit_id} className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                          <button
                            onClick={() => onOpenDocument(document.document_id)}
                            className="text-left font-medium text-cyan-200 hover:text-cyan-100"
                          >
                            {document.original_filename}
                          </button>
                          <p className="text-xs text-slate-400 mt-1">
                            Pages {document.start_page}-{document.end_page}
                            {document.external_id ? ` · ${document.external_id}` : ''}
                          </p>
                          {document.title && <p className="text-sm text-slate-200 mt-2">{document.title}</p>}
                          {document.summary && <p className="text-sm text-slate-400 mt-2 line-clamp-3">{document.summary}</p>}
                          {document.topic_titles.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {document.topic_titles.slice(0, 3).map((topicTitle, index) => (
                                <span
                                  key={`${document.document_unit_id}-${topicTitle}-${index}`}
                                  className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-slate-300"
                                >
                                  {topicTitle}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No detail available for this entity.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[24rem_minmax(0,1fr)]">
        <div className="bg-white/5 border border-white/10 rounded-[24px] shadow-[0_18px_60px_rgba(2,6,23,0.35)] overflow-hidden backdrop-blur-md">
          <div className="border-b border-white/10 px-4 py-3">
            <p className="text-sm font-medium text-slate-100">
              Topics ({visibleTopics.length})
            </p>
          </div>
          <div className="max-h-[70vh] overflow-y-auto divide-y">
            {visibleTopics.length === 0 ? (
              <div className="p-4 text-sm text-slate-400">
                {searchActive ? 'No topics match this search and filter.' : 'No topics match this filter.'}
              </div>
            ) : (
              visibleTopics.map((topic) => (
                <button
                  key={topic.id}
                  onClick={() => setSelectedTopicId(topic.id)}
                  className={`w-full text-left p-4 transition-colors ${
                    topic.id === selectedTopicId
                      ? 'bg-cyan-400/10 shadow-[inset_0_0_0_1px_rgba(103,232,249,0.18)]'
                      : 'hover:bg-white/5'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium text-slate-100 truncate">{topic.title}</p>
                      <p className="text-xs text-slate-400 mt-1">
                        {topic.topic_kind} · {topic.topic_class} · {topic.assignment_count} assignments · {topic.related_document_count}{' '}
                        documents
                      </p>
                    </div>
                    {!topic.is_active && (
                      <span className="shrink-0 px-2 py-1 rounded-full bg-white/10 text-slate-300 text-xs">
                        inactive
                      </span>
                    )}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-[24px] shadow-[0_18px_60px_rgba(2,6,23,0.35)] backdrop-blur-md">
          {!selectedTopicId ? (
            <div className="p-6 text-sm text-slate-400">Select a topic to inspect its linked documents.</div>
          ) : topicLoading ? (
            <div className="p-6 animate-pulse space-y-3">
              <div className="h-6 w-1/2 rounded bg-gray-200"></div>
              <div className="h-24 rounded bg-gray-200"></div>
              <div className="h-48 rounded bg-gray-200"></div>
            </div>
          ) : topicError ? (
            <div className="p-6 text-sm text-red-300">Error loading topic: {(topicError as Error).message}</div>
          ) : topicDetail ? (
            <div className="p-6 space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h3 className="text-xl font-semibold text-white">{topicDetail.topic.title}</h3>
                  <p className="text-sm text-slate-400 mt-1">
                    {topicDetail.topic.topic_kind} · {topicDetail.topic.topic_class} · {topicDetail.topic.assignment_count} assignments ·{' '}
                    {topicDetail.topic.related_document_count} documents
                  </p>
                  {topicDetail.topic.description && (
                    <p className="text-sm text-slate-300 mt-3">{topicDetail.topic.description}</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="px-2 py-1 rounded-full bg-cyan-400/10 text-cyan-200 border border-cyan-300/20">
                    slug: {topicDetail.topic.slug}
                  </span>
                  <span className="px-2 py-1 rounded-full bg-white/10 text-slate-200 border border-white/10">
                    aliases {topicDetail.aliases.length}
                  </span>
                  <span className="px-2 py-1 rounded-full bg-amber-400/10 text-amber-100 border border-amber-300/20">
                    proposals {topicDetail.topic.proposal_count}
                  </span>
                </div>
              </div>

              {topicDetail.aliases.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">Aliases</p>
                  <div className="flex flex-wrap gap-2">
                    {topicDetail.aliases.map((alias) => (
                      <button
                        key={alias}
                        onClick={() => setSearchInput(alias)}
                        className="px-2 py-1 rounded-full bg-white/8 text-slate-200 text-xs border border-white/10 hover:bg-white/12"
                      >
                        {alias}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-3">Linked documents</p>
                {topicDetail.related_documents.length === 0 ? (
                  <p className="text-sm text-slate-400">No linked document units.</p>
                ) : (
                  <div className="space-y-3">
                    {topicDetail.related_documents.map((document) => (
                      <div key={document.document_unit_id} className="border border-white/10 rounded-2xl p-4 bg-slate-950/30">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <button
                              onClick={() => onOpenDocument(document.document_id)}
                              className="text-left font-medium text-cyan-200 hover:text-cyan-100"
                            >
                              {document.original_filename}
                            </button>
                            <p className="text-sm text-slate-400 mt-1">
                              Pages {document.start_page}-{document.end_page}
                              {document.document_type_code ? ` · ${document.document_type_code}` : ''}
                              {document.external_id ? ` · ${document.external_id}` : ''}
                            </p>
                          </div>
                          <div className="text-right text-xs text-slate-400">
                            <p>{document.assignment_role}</p>
                            {document.topic_assignment_confidence !== null && (
                              <p>{(document.topic_assignment_confidence * 100).toFixed(0)}% confidence</p>
                            )}
                          </div>
                        </div>
                        {document.summary && <p className="mt-3 text-sm text-slate-300">{document.summary}</p>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {showProposals && (
        <div className="bg-white/5 border border-white/10 rounded-[24px] shadow-[0_18px_60px_rgba(2,6,23,0.35)] backdrop-blur-md p-6">
          <ProposalList onClose={() => setShowProposals(false)} />
        </div>
      )}
    </div>
  );
}

export default KnowledgeBase;
