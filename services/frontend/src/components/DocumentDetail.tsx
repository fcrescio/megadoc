import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DocumentVersion, DocumentAsset, KnowledgeDocumentUnit, KnowledgeTopicSummary, TopicCreatePayload } from '../types';
import {
  useDocument,
  useDocumentVersions,
  useDocumentOCR,
  useDocumentAssets,
  useDocumentKnowledge,
  useEnsureDocumentKnowledge,
  useKnowledgeTopics,
  useAddDocumentUnitTopicAssignment,
  useDeleteDocumentUnitTopicAssignment,
} from '../hooks/useDocuments';
import { downloadAsset, getDocumentDownloadUrl } from '../api/client';

interface Props {
  documentId: string;
  onBack: () => void;
  initialTab?: 'info' | 'pdf' | 'ocr' | 'knowledge' | 'versions' | 'assets';
}

const ASSIGNMENT_ROLES = [
  { value: 'subject', label: 'Subject' },
  { value: 'document_family', label: 'Document family' },
  { value: 'case_or_issue', label: 'Case / issue' },
  { value: 'person_or_org_context', label: 'Person / org context' },
  { value: 'secondary', label: 'Secondary' },
];

const TOPIC_KINDS = ['entity', 'family', 'issue', 'project', 'context'];

function slugify(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 120);
}

function TopicAssignmentManager({
  unit,
  topics,
}: {
  unit: KnowledgeDocumentUnit;
  topics: KnowledgeTopicSummary[];
}) {
  const addAssignment = useAddDocumentUnitTopicAssignment();
  const deleteAssignment = useDeleteDocumentUnitTopicAssignment();
  const [mode, setMode] = useState<'existing' | 'new'>('existing');
  const [assignmentRole, setAssignmentRole] = useState('document_family');
  const [topicSearch, setTopicSearch] = useState('');
  const [selectedTopicId, setSelectedTopicId] = useState('');
  const [newTitle, setNewTitle] = useState(unit.proposal?.proposed_title ?? unit.title ?? '');
  const [newSlug, setNewSlug] = useState(unit.proposal?.proposed_slug ?? slugify(unit.title ?? ''));
  const [newClass, setNewClass] = useState(unit.proposal?.topic_class ?? 'other');
  const [newKind, setNewKind] = useState(unit.proposal?.proposed_topic_kind ?? 'entity');
  const [description, setDescription] = useState(unit.extracted_summary ?? '');

  const filteredTopics = useMemo(() => {
    const query = topicSearch.trim().toLowerCase();
    const source = topics.filter((topic) => topic.is_active);
    if (!query) {
      return source.slice(0, 6);
    }
    return source
      .filter((topic: KnowledgeTopicSummary) =>
        [topic.title, topic.slug, topic.topic_class, topic.topic_kind].join(' ').toLowerCase().includes(query),
      )
      .slice(0, 6);
  }, [topicSearch, topics]);

  const handleAdd = () => {
    if (mode === 'existing') {
      if (!selectedTopicId) {
        return;
      }
      addAssignment.mutate({
        documentUnitId: unit.id,
        payload: {
          topic_id: selectedTopicId,
          assignment_role: assignmentRole,
          rationale: 'Human review assignment',
        },
      });
      return;
    }
    const createTopic: TopicCreatePayload = {
      slug: newSlug || slugify(newTitle),
      title: newTitle,
      topic_class: newClass,
      topic_kind: newKind,
      description,
      aliases: [],
    };
    addAssignment.mutate({
      documentUnitId: unit.id,
      payload: {
        assignment_role: assignmentRole,
        rationale: 'Human-created topic assignment',
        create_topic: createTopic,
      },
    });
  };

  return (
    <div className="border rounded-lg p-3 bg-slate-50 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setMode('existing')}
          className={`px-2 py-1 rounded-full text-xs ${mode === 'existing' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 border'}`}
        >
          Add existing topic
        </button>
        <button
          onClick={() => setMode('new')}
          className={`px-2 py-1 rounded-full text-xs ${mode === 'new' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 border'}`}
        >
          Create manual topic
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-wide text-gray-500">Assignment role</label>
          <select
            value={assignmentRole}
            onChange={(event) => setAssignmentRole(event.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            {ASSIGNMENT_ROLES.map((role) => (
              <option key={role.value} value={role.value}>
                {role.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {mode === 'existing' ? (
        <div className="space-y-2">
          <input
            value={topicSearch}
            onChange={(event) => setTopicSearch(event.target.value)}
            placeholder="Search existing topics"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <div className="grid gap-2 max-h-40 overflow-y-auto">
            {filteredTopics.map((topic) => (
              <button
                key={topic.id}
                onClick={() => {
                  setSelectedTopicId(topic.id);
                  setTopicSearch(topic.title);
                }}
                className={`text-left rounded-md border px-3 py-2 text-sm ${
                  selectedTopicId === topic.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200 bg-white'
                }`}
              >
                <div className="font-medium">{topic.title}</div>
                <div className="text-xs text-gray-500">
                  {topic.topic_kind} · {topic.topic_class}
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="text-xs uppercase tracking-wide text-gray-500">Title</label>
            <input
              value={newTitle}
              onChange={(event) => {
                setNewTitle(event.target.value);
                setNewSlug(slugify(event.target.value));
              }}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-gray-500">Slug</label>
            <input
              value={newSlug}
              onChange={(event) => setNewSlug(slugify(event.target.value))}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-gray-500">Topic class</label>
            <input
              value={newClass}
              onChange={(event) => setNewClass(event.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-gray-500">Topic kind</label>
            <select
              value={newKind}
              onChange={(event) => setNewKind(event.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              {TOPIC_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="text-xs uppercase tracking-wide text-gray-500">Description</label>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[84px]"
            />
          </div>
        </div>
      )}

      <button
        onClick={handleAdd}
        disabled={addAssignment.isPending || deleteAssignment.isPending}
        className="px-3 py-2 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-50"
      >
        Add assignment
      </button>

      {unit.topic_assignments.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {unit.topic_assignments.map((assignment) => (
            <button
              key={assignment.id}
              onClick={() => deleteAssignment.mutate({ documentUnitId: unit.id, assignmentId: assignment.id })}
              className="px-2 py-1 rounded-full bg-indigo-50 text-indigo-700 text-xs border border-indigo-100"
              title="Remove assignment"
            >
              {assignment.assignment_role}: {assignment.topic_title ?? assignment.topic_slug} ×
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function DocumentDetail({ documentId, onBack, initialTab = 'info' }: Props) {
  const [activeTab, setActiveTab] = useState<'info' | 'pdf' | 'ocr' | 'knowledge' | 'versions' | 'assets'>(initialTab);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  const { data: docData, isLoading: docLoading } = useDocument(documentId);
  const { data: versions } = useDocumentVersions(documentId);
  const { data: ocrResult, isLoading: ocrLoading } = useDocumentOCR(documentId);
  const { data: knowledge, isLoading: knowledgeLoading } = useDocumentKnowledge(documentId);
  const { data: assets } = useDocumentAssets(documentId);
  const { data: knowledgeTopics = [] } = useKnowledgeTopics(true);
  const ensureKnowledge = useEnsureDocumentKnowledge();

  useEffect(() => {
    setActiveTab(initialTab);
  }, [documentId, initialTab]);

  useEffect(() => {
    setSelectedVersionId(null);
  }, [documentId]);

  if (docLoading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-1/3"></div>
        <div className="h-32 bg-gray-200 rounded"></div>
      </div>
    );
  }

  const handleDownloadAsset = async (assetId: string) => {
    try {
      const blob = await downloadAsset(documentId, assetId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `asset-${assetId}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert('Download failed');
    }
  };

  const pdfUrl = getDocumentDownloadUrl(documentId, selectedVersionId ?? undefined, 'inline');
  const selectedVersion = versions?.find((version) => version.id === selectedVersionId) ?? null;

  return (
    <div>
      <button
        onClick={onBack}
        className="mb-4 text-blue-600 hover:text-blue-800 flex items-center"
      >
        ← Back to documents
      </button>

      <div className="bg-white rounded-lg shadow">
        <div className="border-b">
          <nav className="flex -mb-px">
            {(['info', 'pdf', 'ocr', 'knowledge', 'versions', 'assets'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 text-sm font-medium border-b-2 ${
                  activeTab === tab
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-6">
          {activeTab === 'info' && docData && (
            <div className="space-y-4">
              <h2 className="text-xl font-semibold">{docData.original_filename}</h2>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Document ID:</span>
                  <p className="font-mono">{documentId}</p>
                </div>
                {docData.external_id && (
                  <div>
                    <span className="text-gray-500">External ID:</span>
                    <p>{docData.external_id}</p>
                  </div>
                )}
                <div>
                  <span className="text-gray-500">Size:</span>
                  <p>{(docData.size_bytes / 1024).toFixed(1)} KB</p>
                </div>
                <div>
                  <span className="text-gray-500">Created:</span>
                  <p>{new Date(docData.created_at).toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-gray-500">Viewer:</span>
                  <p>{selectedVersion ? `Version ${selectedVersion.version_number}` : 'Latest version'}</p>
                </div>
              </div>
              <button
                onClick={() => setActiveTab('pdf')}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Open PDF Viewer
              </button>
            </div>
          )}

          {activeTab === 'pdf' && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold">
                    {docData?.original_filename ?? 'PDF viewer'}
                  </h2>
                  <p className="text-sm text-gray-500">
                    {selectedVersion ? `Viewing version ${selectedVersion.version_number}` : 'Viewing latest version'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {selectedVersion && (
                    <button
                      onClick={() => setSelectedVersionId(null)}
                      className="px-3 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
                    >
                      Back to latest
                    </button>
                  )}
                  <a
                    href={pdfUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="px-3 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
                  >
                    Open in new tab
                  </a>
                </div>
              </div>

              <div className="rounded-xl overflow-hidden border border-gray-200 bg-gray-950 shadow-inner">
                <iframe
                  key={pdfUrl}
                  src={pdfUrl}
                  title={docData?.original_filename ?? 'PDF document'}
                  className="w-full h-[80vh] bg-white"
                />
              </div>
            </div>
          )}

          {activeTab === 'ocr' && (
            <div>
              {ocrLoading ? (
                <div className="animate-pulse space-y-4">
                  <div className="h-4 bg-gray-200 rounded w-1/4"></div>
                  <div className="h-32 bg-gray-200 rounded"></div>
                </div>
              ) : ocrResult ? (
                <div>
                  <div className="mb-4 text-sm text-gray-500">
                    Engine: {ocrResult.engine_name} {ocrResult.engine_version} |{' '}
                    Pages: {ocrResult.page_count}
                  </div>
                  <div className="border rounded-lg p-4 markdown-body bg-gray-50 max-h-96 overflow-y-auto">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {ocrResult.markdown_text || 'No markdown content'}
                    </ReactMarkdown>
                  </div>
                </div>
              ) : (
                <p className="text-gray-500">No OCR result available yet.</p>
              )}
            </div>
          )}

          {activeTab === 'knowledge' && (
            <div>
              {knowledgeLoading ? (
                <div className="animate-pulse space-y-4">
                  <div className="h-4 bg-gray-200 rounded w-1/4"></div>
                  <div className="h-32 bg-gray-200 rounded"></div>
                </div>
              ) : knowledge && knowledge.scan_units.length > 0 ? (
                <div className="space-y-6">
                  {knowledge.scan_units.map((scanUnit) => (
                    <div key={scanUnit.id} className="border rounded-lg overflow-hidden">
                      <div className="bg-gray-50 px-4 py-3 border-b">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="font-medium text-gray-900">Scan unit</p>
                            <p className="font-mono text-xs text-gray-500">{scanUnit.id}</p>
                          </div>
                          <div className="flex flex-wrap gap-2 text-xs">
                            <span className="px-2 py-1 rounded-full bg-blue-50 text-blue-700">
                              {scanUnit.status}
                            </span>
                            <span className="px-2 py-1 rounded-full bg-gray-100 text-gray-700">
                              {scanUnit.page_count} pages
                            </span>
                            {scanUnit.classification_confidence !== null && (
                              <span className="px-2 py-1 rounded-full bg-emerald-50 text-emerald-700">
                                class {(scanUnit.classification_confidence * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="divide-y">
                        {scanUnit.document_units.map((unit: KnowledgeDocumentUnit) => (
                          <div key={unit.id} className="p-4 space-y-3">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <h3 className="font-semibold text-gray-900">
                                  Unit {unit.ordinal}: {unit.document_type_code ?? 'unknown'}
                                </h3>
                                <p className="text-sm text-gray-500">
                                  Pages {unit.start_page}-{unit.end_page} · {unit.review_status}
                                  {unit.document_type_confidence !== null &&
                                    ` · ${(unit.document_type_confidence * 100).toFixed(0)}% confidence`}
                                </p>
                              </div>
                              <p className="font-mono text-xs text-gray-400">{unit.id}</p>
                            </div>

                            {unit.extracted_summary && (
                              <p className="text-sm text-gray-700 bg-amber-50 border border-amber-100 rounded p-3">
                                {unit.extracted_summary}
                              </p>
                            )}

                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                                Topics
                              </p>
                              {unit.topic_assignments.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                  {unit.topic_assignments.map((assignment) => (
                                    <span
                                      key={assignment.id}
                                      title={assignment.rationale ?? undefined}
                                      className="px-2 py-1 rounded-full bg-indigo-50 text-indigo-700 text-xs"
                                    >
                                      {assignment.assignment_role}: {assignment.topic_title ?? assignment.topic_slug}
                                      {assignment.confidence !== null &&
                                        ` · ${(assignment.confidence * 100).toFixed(0)}%`}
                                    </span>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-sm text-gray-500">No topic assignment.</p>
                              )}
                              {unit.proposal && (
                                <div className="mt-2">
                                  <span
                                    className="px-2 py-1 rounded-full bg-orange-50 text-orange-700 text-xs"
                                    title={unit.proposal.rationale ?? undefined}
                                  >
                                    Proposed: {unit.proposal.proposed_title} · {unit.proposal.proposal_status}
                                  </span>
                                </div>
                              )}
                            </div>

                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                                Review actions
                              </p>
                              <TopicAssignmentManager unit={unit} topics={knowledgeTopics} />
                            </div>

                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                                Entities
                              </p>
                              {unit.entities.length > 0 ? (
                                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                                  {unit.entities.map((entity) => (
                                    <div key={entity.id} className="border rounded p-2 bg-white">
                                      <p className="text-xs text-gray-500">{entity.entity_type}</p>
                                      <p className="text-sm text-gray-900 truncate" title={entity.entity_value}>
                                        {entity.entity_value}
                                      </p>
                                      {entity.normalized_value && (
                                        <p className="text-xs text-gray-400 truncate" title={entity.normalized_value}>
                                          {entity.normalized_value}
                                        </p>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-sm text-gray-500">No entities extracted.</p>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-4">
                  <p className="text-gray-500">No knowledge result available yet.</p>
                  {ocrResult ? (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                      <p className="text-sm text-amber-900">
                        OCR is available for this document, but the knowledge pipeline has not produced a scan yet.
                      </p>
                      <button
                        onClick={() => ensureKnowledge.mutate(documentId)}
                        disabled={ensureKnowledge.isPending}
                        className="mt-3 px-4 py-2 rounded-md bg-amber-600 text-white text-sm hover:bg-amber-700 disabled:opacity-60"
                      >
                        {ensureKnowledge.isPending ? 'Queueing knowledge...' : 'Process knowledge now'}
                      </button>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500">Knowledge starts only after OCR succeeds.</p>
                  )}
                </div>
              )}
            </div>
          )}

          {activeTab === 'versions' && (
            <div>
              {versions && versions.length === 0 ? (
                <p className="text-gray-500">No versions found.</p>
              ) : (
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Version</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Created</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {versions?.map((v: DocumentVersion) => (
                      <tr key={v.id}>
                        <td className="px-4 py-2 text-sm">{v.version_number}</td>
                        <td className="px-4 py-2 text-sm text-gray-500">
                          {new Date(v.created_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-2 text-sm">
                          <button
                            onClick={() => {
                              setSelectedVersionId(v.id);
                              setActiveTab('pdf');
                            }}
                            className="text-blue-600 hover:text-blue-800"
                          >
                            View
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {activeTab === 'assets' && (
            <div>
              {assets && assets.length === 0 ? (
                <p className="text-gray-500">No assets found.</p>
              ) : (
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Type</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Created</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {assets?.map((a: DocumentAsset) => (
                      <tr key={a.id}>
                        <td className="px-4 py-2 text-sm">{a.asset_type}</td>
                        <td className="px-4 py-2 text-sm text-gray-500">
                          {new Date(a.created_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-2 text-sm">
                          <button
                            onClick={() => handleDownloadAsset(a.id)}
                            className="text-blue-600 hover:text-blue-800"
                          >
                            Download
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DocumentDetail;
