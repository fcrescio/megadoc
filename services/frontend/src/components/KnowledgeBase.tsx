import { useEffect, useMemo, useState } from 'react';
import {
  useKnowledgeTopic,
  useKnowledgeTopics,
  useRunKnowledgeConsolidation,
} from '../hooks/useDocuments';

interface Props {
  onOpenDocument: (documentId: string) => void;
}

function KnowledgeBase({ onOpenDocument }: Props) {
  const [includeInactive, setIncludeInactive] = useState(false);
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const [topicClassFilter, setTopicClassFilter] = useState<string>('all');
  const { data: topics, isLoading, error } = useKnowledgeTopics(includeInactive);
  const { data: topicDetail, isLoading: topicLoading, error: topicError } = useKnowledgeTopic(selectedTopicId);
  const consolidate = useRunKnowledgeConsolidation();

  const visibleTopics = useMemo(() => {
    if (!topics) {
      return [];
    }
    if (topicClassFilter === 'all') {
      return topics;
    }
    return topics.filter((topic) => topic.topic_class === topicClassFilter);
  }, [topicClassFilter, topics]);

  const topicClasses = useMemo(() => {
    return Array.from(new Set((topics ?? []).map((topic) => topic.topic_class))).sort();
  }, [topics]);

  const stats = useMemo(() => {
    const source = topics ?? [];
    return {
      totalTopics: source.length,
      totalAssignments: source.reduce((acc, topic) => acc + topic.assignment_count, 0),
      totalAliases: source.reduce((acc, topic) => acc + topic.alias_count, 0),
      topicClasses: topicClasses.length,
    };
  }, [topicClasses.length, topics]);

  useEffect(() => {
    if (!visibleTopics.length) {
      setSelectedTopicId(null);
      return;
    }
    if (!selectedTopicId || !visibleTopics.some((topic) => topic.id === selectedTopicId)) {
      setSelectedTopicId(visibleTopics[0].id);
    }
  }, [selectedTopicId, visibleTopics]);

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
      <div className="rounded-[28px] border border-cyan-300/15 bg-slate-950/45 backdrop-blur-xl shadow-[0_24px_80px_rgba(8,47,73,0.45)] overflow-hidden">
        <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr] p-6 lg:p-8">
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-cyan-300/75 mb-3">Knowledge Atlas</p>
            <h2 className="text-3xl lg:text-4xl font-semibold text-white">Consolidated topics across the whole corpus</h2>
            <p className="text-sm text-slate-300 mt-3 max-w-2xl">
              Browse consolidated topics, aliases and linked document units.
            </p>
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
            Browse consolidated topics, aliases and linked document units.
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

      <div className="grid gap-4 lg:grid-cols-[24rem_minmax(0,1fr)]">
        <div className="bg-white/5 border border-white/10 rounded-[24px] shadow-[0_18px_60px_rgba(2,6,23,0.35)] overflow-hidden backdrop-blur-md">
          <div className="border-b border-white/10 px-4 py-3">
            <p className="text-sm font-medium text-slate-100">
              Topics ({visibleTopics.length})
            </p>
          </div>
          <div className="max-h-[70vh] overflow-y-auto divide-y">
            {visibleTopics.length === 0 ? (
              <div className="p-4 text-sm text-slate-400">No topics match this filter.</div>
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
                        {topic.topic_class} · {topic.assignment_count} assignments · {topic.related_document_count}{' '}
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
                    {topicDetail.topic.topic_class} · {topicDetail.topic.assignment_count} assignments ·{' '}
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
                      <span key={alias} className="px-2 py-1 rounded-full bg-white/8 text-slate-200 text-xs border border-white/10">
                        {alias}
                      </span>
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
    </div>
  );
}

export default KnowledgeBase;
