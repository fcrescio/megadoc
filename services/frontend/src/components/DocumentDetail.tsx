import { memo, useEffect, useMemo, useState } from 'react';
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
  useEnsureDocumentSpecialists,
  useKnowledgeTopics,
  useAddDocumentUnitTopicAssignment,
  useDeleteDocumentUnitTopicAssignment,
  useDeleteDocumentUnit,
  useReingestDocument,
} from '../hooks/useDocuments';
import { downloadAsset, getDocumentDownloadUrl, getSpecialistResultExportUrl } from '../api/client';

interface Props {
  documentId: string;
  onBack: () => void;
  initialTab?: 'info' | 'pdf' | 'ocr' | 'knowledge' | 'versions' | 'assets';
}

const ASSIGNMENT_ROLES = [
  { value: 'subject', label: 'Soggetto' },
  { value: 'document_family', label: 'Famiglia documento' },
  { value: 'case_or_issue', label: 'Pratica / problema' },
  { value: 'person_or_org_context', label: 'Persona / contesto organizzativa' },
  { value: 'secondary', label: 'Secondario' },
];

const TOPIC_KINDS = ['entity', 'family', 'issue', 'project', 'context'];

function formatDate(value: unknown) {
  if (typeof value !== 'string' || !value) {
    return 'n/d';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString('it-IT');
}

function formatCurrency(value: unknown) {
  if (typeof value !== 'number') {
    return 'n/d';
  }
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
  }).format(value);
}

function UtilityBillSpecialistCard({
  result,
  links,
}: {
  result: Record<string, unknown>;
  links: KnowledgeDocumentUnit['outgoing_links'];
}) {
  return (
    <div className="rounded-xl border border-sky-100 bg-sky-50/80 p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-700">Utility Bill</p>
          <h4 className="text-base font-semibold text-slate-900">
            {typeof result.issuer === 'string' && result.issuer ? result.issuer : 'Fornitore non identificato'}
          </h4>
        </div>
        <div className="rounded-full bg-white/90 px-3 py-1 text-sm font-medium text-sky-700 border border-sky-100">
          {typeof result.service_type === 'string' && result.service_type ? result.service_type : 'sconosciuto'}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {typeof result.__result_id === 'string' && (
          <>
            <a
              href={getSpecialistResultExportUrl(result.__result_id, 'json')}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-sky-200 bg-white px-3 py-1 text-xs font-medium text-sky-700 hover:bg-sky-50"
            >
              Export JSON
            </a>
            <a
              href={getSpecialistResultExportUrl(result.__result_id, 'csv')}
              className="rounded-full border border-sky-200 bg-white px-3 py-1 text-xs font-medium text-sky-700 hover:bg-sky-50"
            >
              Export CSV
            </a>
          </>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-lg bg-white p-3 border border-sky-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Emissione</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{formatDate(result.issue_date)}</p>
        </div>
        <div className="rounded-lg bg-white p-3 border border-sky-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Scadenza</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{formatDate(result.due_date)}</p>
        </div>
        <div className="rounded-lg bg-white p-3 border border-sky-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Importo totale</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{formatCurrency(result.total_amount)}</p>
        </div>
        <div className="rounded-lg bg-white p-3 border border-sky-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Intestazione</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{String(result.account_holder || 'n/d')}</p>
        </div>
        <div className="rounded-lg bg-white p-3 border border-sky-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Numero documento</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{String(result.document_number || 'n/d')}</p>
        </div>
        <div className="rounded-lg bg-white p-3 border border-sky-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Stato pagamento</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{String(result.payment_status || 'sconosciuto')}</p>
        </div>
      </div>

      {Boolean(result.billing_period_from || result.billing_period_to || result.pod_pdr_or_supply_code || result.supply_reference) && (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg bg-white p-3 border border-sky-100">
            <p className="text-xs uppercase tracking-wide text-slate-500">Periodo competenza</p>
            <p className="mt-1 text-sm text-slate-900">
              {formatDate(result.billing_period_from)} {result.billing_period_to ? `→ ${formatDate(result.billing_period_to)}` : ''}
            </p>
          </div>
          <div className="rounded-lg bg-white p-3 border border-sky-100">
            <p className="text-xs uppercase tracking-wide text-slate-500">Riferimento fornitura</p>
            <p className="mt-1 text-sm text-slate-900 break-words">
              {String(result.pod_pdr_or_supply_code || result.supply_reference || 'n/d')}
            </p>
          </div>
        </div>
      )}

      {links.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Collegamenti</p>
          <div className="flex flex-wrap gap-2">
            {links.map((link) => (
              <span key={link.id} className="rounded-full bg-white px-3 py-1 text-xs text-slate-700 border border-sky-100">
                {link.link_type.replace(/_/g, ' ')}
                {' · '}
                {link.target_document_type_code ?? 'documento'}: {link.target_title ?? link.target_document_unit_id}
                {link.confidence !== null ? ` · ${(link.confidence * 100).toFixed(0)}%` : ''}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AccountingSpecialistCard({ result }: { result: Record<string, unknown> }) {
  const tables = Array.isArray(result.tables) ? (result.tables as Record<string, unknown>[]) : [];
  const sections = Array.isArray(result.sections) ? (result.sections as Record<string, unknown>[]) : [];
  const validationChecks = Array.isArray(result.validation_checks)
    ? (result.validation_checks as Record<string, unknown>[])
    : [];
  const [activeSectionId, setActiveSectionId] = useState<string | null>(
    typeof sections[0]?.section_id === 'string' ? sections[0].section_id : null,
  );
  const sectionsKey = useMemo(() => sections.map((s) => s.section_id as string).join(','), [sections]);
  useEffect(() => {
    if (!sections.length) {
      setActiveSectionId(null);
      return;
    }
    if (!sections.some((section) => section.section_id === activeSectionId)) {
      setActiveSectionId(typeof sections[0].section_id === 'string' ? sections[0].section_id : null);
    }
  }, [sectionsKey]);
  const visibleTables = activeSectionId
    ? tables.filter((table) => table.section_id === activeSectionId)
    : tables;

  return (
    <div className="rounded-xl border border-emerald-100 bg-emerald-50/80 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-emerald-700">Accounting Statement</p>
          <h4 className="text-base font-semibold text-slate-900">
            {typeof result.statement_type === 'string' && result.statement_type ? result.statement_type : 'dichiarazione'}
          </h4>
        </div>
        <div className="rounded-full bg-white/90 px-3 py-1 text-sm font-medium text-emerald-700 border border-emerald-100">
          {tables.length} tabelle
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {typeof result.__result_id === 'string' && (
          <>
            <a
              href={getSpecialistResultExportUrl(result.__result_id, 'json')}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-emerald-200 bg-white px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
            >
              Export JSON
            </a>
            <a
              href={getSpecialistResultExportUrl(result.__result_id, 'csv')}
              className="rounded-full border border-emerald-200 bg-white px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
            >
              Export CSV
            </a>
          </>
        )}
      </div>

      {sections.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Sezioni</p>
          <div className="flex flex-wrap gap-2">
            {sections.map((section) => (
              <button
                key={String(section.section_id)}
                type="button"
                onClick={() => setActiveSectionId(String(section.section_id))}
                className={`rounded-full border px-3 py-1 text-xs font-medium ${
                  activeSectionId === section.section_id
                    ? 'border-emerald-300 bg-emerald-600 text-white'
                    : 'border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50'
                }`}
              >
                {String(section.label || 'Sezione')} · {String(section.table_count || 0)}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-lg bg-white p-3 border border-emerald-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Periodo</p>
          <p className="mt-1 text-sm font-medium text-slate-900">
            {formatDate(result.accounting_period_from)} {result.accounting_period_to ? `→ ${formatDate(result.accounting_period_to)}` : ''}
          </p>
        </div>
        <div className="rounded-lg bg-white p-3 border border-emerald-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Valuta</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{String(result.currency || 'EUR')}</p>
        </div>
        <div className="rounded-lg bg-white p-3 border border-emerald-100">
          <p className="text-xs uppercase tracking-wide text-slate-500">Tipo</p>
          <p className="mt-1 text-sm font-medium text-slate-900">{String(result.statement_type || 'n/d')}</p>
        </div>
      </div>

      {validationChecks.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Verifiche</p>
          <div className="grid gap-2">
            {validationChecks.map((check: Record<string, unknown>, index: number) => (
              <div key={index} className="rounded-lg bg-white border border-emerald-100 px-3 py-2 text-sm">
                <span className={`font-medium ${check.status === 'pass' ? 'text-emerald-700' : 'text-slate-900'}`}>
                  {String(check.check_type || 'check')}
                </span>
                {check.details ? (
                  <span className="text-slate-600"> · {String(check.details)}</span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {tables.length > 0 && (
        <div className="space-y-4">
          {visibleTables.map((table: Record<string, unknown>, tableIndex: number) => {
            const headers = Array.isArray(table.headers) ? (table.headers as unknown[]) : [];
            const rows = Array.isArray(table.rows) ? (table.rows as Record<string, unknown>[]) : [];
            const previewRows = rows.slice(0, 6);
            return (
              <div key={tableIndex} className="rounded-lg border border-emerald-100 bg-white overflow-hidden">
                <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-emerald-100 bg-emerald-50/50">
                  <div className="text-sm font-medium text-slate-900">
                    {String(table.section_label || table.table_type || 'table')}
                    <span className="ml-2 text-xs font-normal text-slate-500">{String(table.table_id || '')}</span>
                  </div>
                  <div className="text-xs text-slate-500">{rows.length} righe</div>
                </div>
                {headers.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="bg-slate-50">
                        <tr>
                          {headers.map((header: unknown, headerIndex: number) => (
                            <th key={headerIndex} className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                              {String(header)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {previewRows.map((row: Record<string, unknown>, rowIndex: number) => {
                          const cells = row.cells && typeof row.cells === 'object' ? (row.cells as Record<string, unknown>) : {};
                          return (
                            <tr key={rowIndex}>
                              {headers.map((header: unknown, headerIndex: number) => (
                                <td key={headerIndex} className="px-3 py-2 text-slate-700 align-top whitespace-pre-wrap">
                                  {String(cells[String(header)] ?? '')}
                                </td>
                              ))}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="px-3 py-3 text-sm text-slate-500">Tabella riconosciuta senza intestazioni affidabili.</div>
                )}
                {rows.length > previewRows.length && (
                  <div className="px-3 py-2 text-xs text-slate-500 border-t border-slate-100">
                    Preview limitata alle prime {previewRows.length} righe.
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

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
    const sortedTopics = [...topics].sort((left, right) => {
      const leftRank = (left.is_active ? 2 : 0) + (left.canonical ? 1 : 0);
      const rightRank = (right.is_active ? 2 : 0) + (right.canonical ? 1 : 0);
      if (leftRank !== rightRank) {
        return rightRank - leftRank;
      }
      return left.title.localeCompare(right.title, 'it');
    });
    const matchingTopics = query
      ? sortedTopics.filter((topic: KnowledgeTopicSummary) =>
        [topic.title, topic.slug, topic.topic_class, topic.topic_kind].join(' ').toLowerCase().includes(query),
      )
      : sortedTopics;
    return matchingTopics.slice(0, 8);
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
          rationale: 'Assegnazione tramite revisione umana',
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
            onChange={(event) => {
              setTopicSearch(event.target.value);
              setSelectedTopicId('');
            }}
            placeholder="Cerca topic esistenti"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <div className="grid gap-2 max-h-40 overflow-y-auto">
            {filteredTopics.length > 0 ? (
              filteredTopics.map((topic) => (
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
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-gray-500">
                    <span>{topic.topic_kind} · {topic.topic_class}</span>
                    {!topic.is_active && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700 border border-amber-100">
                        inattivo
                      </span>
                    )}
                    {!topic.canonical && (
                      <span className="rounded-full bg-slate-50 px-2 py-0.5 text-slate-600 border border-slate-100">
                        provvisorio
                      </span>
                    )}
                  </div>
                </button>
              ))
            ) : (
              <p className="text-xs text-gray-400 italic px-1">
                {topicSearch.trim()
                  ? 'Nessun topic trovato. Prova a cambiare ricerca o passa a "Create manual topic".'
                  : 'Nessun topic disponibile.'}
              </p>
            )}
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
        disabled={
          addAssignment.isPending
          || deleteAssignment.isPending
          || (mode === 'existing' && !selectedTopicId)
        }
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
              title="Rimuovi assegnazione"
            >
              {assignment.assignment_role}: {assignment.topic_title ?? assignment.topic_slug} ×
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const TopicAssignmentManagerMemo = memo(TopicAssignmentManager);

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
  const ensureSpecialists = useEnsureDocumentSpecialists();
  const reingest = useReingestDocument();
  const deleteDocUnit = useDeleteDocumentUnit();

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
      alert('Download non riuscito');
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
                  <p>{selectedVersion ? `Versione ${selectedVersion.version_number}` : 'Ultima versione'}</p>
                </div>
              </div>

              {/* Ingestion status */}
              {docData.ingestion_status && (
                <div className="border-t border-slate-200 pt-4">
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">Stato ingestione</h3>
                  <div className="flex items-center gap-3">
                    <span className={`inline-flex items-center px-2.5 py-1 text-xs font-medium rounded-full border ${
                      docData.ingestion_status === 'succeeded'
                        ? 'bg-green-100 text-green-700 border-green-200'
                        : docData.ingestion_status === 'failed'
                        ? 'bg-red-100 text-red-700 border-red-200'
                        : docData.ingestion_status === 'running'
                        ? 'bg-blue-100 text-blue-700 border-blue-200'
                        : 'bg-slate-100 text-slate-600 border-slate-200'
                    }`}>
                      {docData.ingestion_status}
                    </span>
                    {docData.ingestion_status === 'failed' && (
                      <button
                        onClick={() => reingest.mutate({ documentId })}
                        disabled={reingest.isPending}
                        className="px-3 py-1.5 text-xs font-medium rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
                      >
                        {reingest.isPending ? 'Reinserimento...' : 'Riprova ingestione'}
                      </button>
                    )}
                  </div>
                  {docData.ingestion_error && (
                    <p className="mt-1.5 text-xs text-red-600 font-mono bg-red-50 rounded p-2 border border-red-100">
                      {docData.ingestion_error}
                    </p>
                  )}
                </div>
              )}

              {/* Preflight / orientation info */}
              {knowledge && knowledge.scan_units.length > 0 && (
                <div className="border-t border-slate-200 pt-4">
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">Preflight / Orientamento</h3>
                  <div className="space-y-2">
                    {knowledge.scan_units.map((su) => (
                      <div key={su.id} className="text-sm bg-slate-50 rounded-lg p-3 border border-slate-200">
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="font-medium text-slate-700">Scansione fisica</span>
                          <span className="text-xs text-slate-400">
                            {su.page_count} pagine
                            {su.document_units.length > 0 && ` · ${su.document_units.length} documenti`}
                          </span>
                          {su.preflight && (
                            <div className="flex flex-wrap gap-1 ml-auto">
                              {su.preflight.rotation_applied != null && su.preflight.rotation_applied !== 0 && (
                                <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full bg-amber-100 text-amber-700 border border-amber-200">
                                  Ruotato {su.preflight.rotation_applied}°
                                </span>
                              )}
                              {su.preflight.page_order_reversed && (
                                <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full bg-orange-100 text-orange-700 border border-orange-200">
                                  Ordine invertito
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                        {su.preflight && (
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-600">
                            <div>Rotazione applicata: <span className="font-mono">{su.preflight.rotation_applied ?? 'n/d'}</span></div>
                            <div>Ordine pagine invertito: <span className="font-mono">{su.preflight.page_order_reversed ? 'Si' : 'No'}</span></div>
                            <div>Backend orientamento: <span className="font-mono">{su.preflight.orientation_backend ?? 'n/d'}</span></div>
                            <div>Orientamento applicato: <span className="font-mono">{su.preflight.orientation_applied ? 'Si' : 'No'}</span></div>
                            {su.preflight.dominant_declared_rotation != null && (
                              <div>Rotazione dichiarata: <span className="font-mono">{su.preflight.dominant_declared_rotation}°</span></div>
                            )}
                            {su.preflight.flags.length > 0 && (
                              <div className="col-span-2">
                                <span className="text-slate-500">Flags:</span>{' '}
                                <span className="font-mono">{su.preflight.flags.join(', ') || 'nessuno'}</span>
                              </div>
                            )}
                            {su.preflight.warnings.length > 0 && (
                              <div className="col-span-2">
                                <span className="text-slate-500">Warning:</span>{' '}
                                <span className="font-mono text-amber-600">{su.preflight.warnings.join(', ') || 'nessuno'}</span>
                              </div>
                            )}
                          </div>
                        )}
                        {!su.preflight && (
                          <p className="text-xs text-slate-400 italic">Nessun dato preflight disponibile</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

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
                    {selectedVersion ? `Visualizzazione della versione ${selectedVersion.version_number}` : "Visualizzazione dell'ultima versione"}
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
                      {ocrResult.markdown_text || 'Nessun contenuto markdown'}
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
                  <div className="flex items-center justify-end">
                    <button
                      onClick={() => ensureSpecialists.mutate(documentId)}
                      disabled={ensureSpecialists.isPending}
                      className="px-3 py-2 rounded-md border border-slate-300 text-slate-700 text-sm hover:bg-slate-50 disabled:opacity-60"
                    >
                      {ensureSpecialists.isPending ? 'Specialisti in coda...' : 'Estrazione specialistica'}
                    </button>
                  </div>
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
                                  Unit {unit.ordinal}: {unit.document_type_code ?? 'sconosciuto'}
                                </h3>
                                <p className="text-sm text-gray-500">
                                  Pages {unit.start_page}-{unit.end_page} · {unit.review_status}
                                  {unit.document_type_confidence !== null &&
                                    ` · ${(unit.document_type_confidence * 100).toFixed(0)}% confidence`}
                                </p>
                              </div>
                              <div className="flex items-center gap-2">
                                <p className="font-mono text-xs text-gray-400">{unit.id}</p>
                                <button
                                  onClick={() => {
                                    if (window.confirm(`Sopprimere la document unit ${unit.ordinal} (${unit.document_type_code ?? 'sconosciuto'}) e tutti i dati derivati?`)) {
                                      deleteDocUnit.mutate(unit.id);
                                    }
                                  }}
                                  disabled={deleteDocUnit.isPending}
                                  className="px-2 py-1 text-xs font-medium rounded-md bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 disabled:opacity-60"
                                  title="Elimina questa document unit e tutti i dati derivati"
                                >
                                  Sopprimi
                                </button>
                              </div>
                            </div>

                            {unit.extracted_summary && (
                              <p className="text-sm text-gray-700 bg-amber-50 border border-amber-100 rounded p-3">
                                {unit.extracted_summary}
                              </p>
                            )}

                            {unit.specialist_results.length > 0 && (
                              <div className="space-y-3">
                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                                  Specialized extraction
                                </p>
                                {unit.specialist_results.map((specialistResult) => (
                                  <div key={specialistResult.id} className="space-y-2">
                                    <div className="flex flex-wrap gap-2 text-xs">
                                      <span className="px-2 py-1 rounded-full bg-slate-100 text-slate-700">
                                        {specialistResult.specialist_type}
                                      </span>
                                      <span className="px-2 py-1 rounded-full bg-slate-100 text-slate-700">
                                        {specialistResult.review_status}
                                      </span>
                                      {specialistResult.confidence !== null && (
                                        <span className="px-2 py-1 rounded-full bg-slate-100 text-slate-700">
                                          {(specialistResult.confidence * 100).toFixed(0)}%
                                        </span>
                                      )}
                                    </div>
                                    {specialistResult.specialist_type === 'utility_bill' ? (
                                      <UtilityBillSpecialistCard
                                        result={{ ...specialistResult.result_json, __result_id: specialistResult.id }}
                                        links={unit.outgoing_links}
                                      />
                                    ) : specialistResult.specialist_type === 'accounting_statement' ? (
                                      <AccountingSpecialistCard
                                        result={{ ...specialistResult.result_json, __result_id: specialistResult.id }}
                                      />
                                    ) : null}
                                  </div>
                                ))}
                              </div>
                            )}

                            {unit.specialist_jobs.length > 0 && (
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                                  Specialist jobs
                                </p>
                                <div className="flex flex-wrap gap-2">
                                  {unit.specialist_jobs.map((job) => (
                                    <span key={job.id} className="px-2 py-1 rounded-full bg-slate-100 text-slate-700 text-xs">
                                      {job.specialist_type}: {job.status}
                                    </span>
                                  ))}
                                </div>
                              </div>
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
                              <TopicAssignmentManagerMemo unit={unit} topics={knowledgeTopics} />
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
                        {ensureKnowledge.isPending ? 'Conoscenza in coda...' : 'Elabora conoscenza ora'}
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
