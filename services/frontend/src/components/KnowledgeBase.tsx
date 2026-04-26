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
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Knowledge Base</h2>
          <p className="text-sm text-gray-500">
            Browse consolidated topics, aliases and linked document units.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-gray-600 flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(event) => setIncludeInactive(event.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Show inactive
          </label>
          <select
            value={topicClassFilter}
            onChange={(event) => setTopicClassFilter(event.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
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
            className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-60"
          >
            {consolidate.isPending ? 'Consolidating...' : 'Run Consolidation'}
          </button>
        </div>
      </div>

      {consolidate.data && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          Topics {consolidate.data.topics_before} → {consolidate.data.topics_after}, merged{' '}
          {consolidate.data.topics_merged}, retargeted assignments {consolidate.data.assignments_retargeted}, aliases{' '}
          {consolidate.data.aliases_created}.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[24rem_minmax(0,1fr)]">
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="border-b px-4 py-3">
            <p className="text-sm font-medium text-gray-900">
              Topics ({visibleTopics.length})
            </p>
          </div>
          <div className="max-h-[70vh] overflow-y-auto divide-y">
            {visibleTopics.length === 0 ? (
              <div className="p-4 text-sm text-gray-500">No topics match this filter.</div>
            ) : (
              visibleTopics.map((topic) => (
                <button
                  key={topic.id}
                  onClick={() => setSelectedTopicId(topic.id)}
                  className={`w-full text-left p-4 transition-colors ${
                    topic.id === selectedTopicId ? 'bg-blue-50' : 'hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium text-gray-900 truncate">{topic.title}</p>
                      <p className="text-xs text-gray-500 mt-1">
                        {topic.topic_class} · {topic.assignment_count} assignments · {topic.related_document_count}{' '}
                        documents
                      </p>
                    </div>
                    {!topic.is_active && (
                      <span className="shrink-0 px-2 py-1 rounded-full bg-gray-100 text-gray-600 text-xs">
                        inactive
                      </span>
                    )}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow">
          {!selectedTopicId ? (
            <div className="p-6 text-sm text-gray-500">Select a topic to inspect its linked documents.</div>
          ) : topicLoading ? (
            <div className="p-6 animate-pulse space-y-3">
              <div className="h-6 w-1/2 rounded bg-gray-200"></div>
              <div className="h-24 rounded bg-gray-200"></div>
              <div className="h-48 rounded bg-gray-200"></div>
            </div>
          ) : topicError ? (
            <div className="p-6 text-sm text-red-700">Error loading topic: {(topicError as Error).message}</div>
          ) : topicDetail ? (
            <div className="p-6 space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h3 className="text-xl font-semibold text-gray-900">{topicDetail.topic.title}</h3>
                  <p className="text-sm text-gray-500 mt-1">
                    {topicDetail.topic.topic_class} · {topicDetail.topic.assignment_count} assignments ·{' '}
                    {topicDetail.topic.related_document_count} documents
                  </p>
                  {topicDetail.topic.description && (
                    <p className="text-sm text-gray-700 mt-3">{topicDetail.topic.description}</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="px-2 py-1 rounded-full bg-indigo-50 text-indigo-700">
                    slug: {topicDetail.topic.slug}
                  </span>
                  <span className="px-2 py-1 rounded-full bg-gray-100 text-gray-700">
                    aliases {topicDetail.aliases.length}
                  </span>
                  <span className="px-2 py-1 rounded-full bg-amber-50 text-amber-700">
                    proposals {topicDetail.topic.proposal_count}
                  </span>
                </div>
              </div>

              {topicDetail.aliases.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Aliases</p>
                  <div className="flex flex-wrap gap-2">
                    {topicDetail.aliases.map((alias) => (
                      <span key={alias} className="px-2 py-1 rounded-full bg-gray-100 text-gray-700 text-xs">
                        {alias}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">Linked documents</p>
                {topicDetail.related_documents.length === 0 ? (
                  <p className="text-sm text-gray-500">No linked document units.</p>
                ) : (
                  <div className="space-y-3">
                    {topicDetail.related_documents.map((document) => (
                      <div key={document.document_unit_id} className="border rounded-lg p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <button
                              onClick={() => onOpenDocument(document.document_id)}
                              className="text-left font-medium text-blue-700 hover:text-blue-900"
                            >
                              {document.original_filename}
                            </button>
                            <p className="text-sm text-gray-500 mt-1">
                              Pages {document.start_page}-{document.end_page}
                              {document.document_type_code ? ` · ${document.document_type_code}` : ''}
                              {document.external_id ? ` · ${document.external_id}` : ''}
                            </p>
                          </div>
                          <div className="text-right text-xs text-gray-500">
                            <p>{document.assignment_role}</p>
                            {document.topic_assignment_confidence !== null && (
                              <p>{(document.topic_assignment_confidence * 100).toFixed(0)}% confidence</p>
                            )}
                          </div>
                        </div>
                        {document.summary && <p className="mt-3 text-sm text-gray-700">{document.summary}</p>}
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
