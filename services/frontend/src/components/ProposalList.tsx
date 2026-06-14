import { memo, useMemo, useState } from 'react';
import {
  useApproveTopicProposal,
  useKnowledgeTopics,
  useRejectTopicProposal,
  useTopicProposals,
} from '../hooks/useDocuments';
import type { KnowledgeTopicProposal, KnowledgeTopicSummary, TopicCreatePayload } from '../types';
import { Virtuoso } from 'react-virtuoso';

interface Props {
  onClose: () => void;
  initialProposals?: KnowledgeTopicProposal[];
}

const ASSIGNMENT_ROLES = [
  { value: 'subject', label: 'Soggetto' },
  { value: 'document_family', label: 'Famiglia documento' },
  { value: 'case_or_issue', label: 'Pratica / problema' },
  { value: 'person_or_org_context', label: 'Persona / contesto organizzativa' },
  { value: 'secondary', label: 'Secondario' },
];

const TOPIC_KINDS = ['entity', 'family', 'issue', 'project', 'context'];
const TOPIC_OPTION_LIMIT = 80;

function slugify(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 120);
}

const ProposalCard = memo(function ProposalCard({
  proposal,
  topicOptions,
  onApprove,
  onReject,
  busy,
  expanded,
  onToggleExpanded,
}: {
  proposal: KnowledgeTopicProposal;
  topicOptions: KnowledgeTopicSummary[];
  onApprove: (proposalId: string, payload: {
    action: 'approve_new_topic' | 'merge_into_existing' | 'add_secondary_topic';
    assignment_role: string;
    target_topic_id?: string;
    create_topic?: TopicCreatePayload;
  }) => void;
  onReject: (proposalId: string) => void;
  busy: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
}) {
  const [mode, setMode] = useState<'merge_into_existing' | 'approve_new_topic' | 'add_secondary_topic'>(
    proposal.matched_existing_topic_id ? 'merge_into_existing' : 'approve_new_topic',
  );
  const [assignmentRole, setAssignmentRole] = useState('subject');
  const [topicSearch, setTopicSearch] = useState('');
  const [selectedTopicId, setSelectedTopicId] = useState<string>(proposal.matched_existing_topic_id ?? '');
  const [newTitle, setNewTitle] = useState(proposal.proposed_title);
  const [newSlug, setNewSlug] = useState(proposal.proposed_slug);
  const [newKind, setNewKind] = useState(proposal.proposed_topic_kind);
  const [description, setDescription] = useState(proposal.description ?? '');
  const [confirmReject, setConfirmReject] = useState(false);

  const filteredTopicOptions = useMemo(() => {
    const query = topicSearch.trim().toLowerCase();
    const matchingTopics = query
      ? topicOptions.filter((topic) =>
        [topic.title, topic.slug, topic.topic_class, topic.topic_kind].join(' ').toLowerCase().includes(query),
      )
      : topicOptions;
    return matchingTopics.slice(0, TOPIC_OPTION_LIMIT);
  }, [topicSearch, topicOptions]);

  const selectedTopic = useMemo(
    () => topicOptions.find((topic) => topic.id === selectedTopicId) ?? null,
    [selectedTopicId, topicOptions],
  );
  const targetTopicSelectionIsValid =
    mode === 'approve_new_topic'
    || selectedTopic !== null;

  const handleApprove = () => {
    if (mode === 'merge_into_existing' || mode === 'add_secondary_topic') {
      if (!selectedTopicId) {
        return;
      }
      onApprove(proposal.id, {
        action: mode,
        assignment_role: assignmentRole,
        target_topic_id: selectedTopicId,
      });
      return;
    }
    onApprove(proposal.id, {
      action: 'approve_new_topic',
      assignment_role: assignmentRole,
      create_topic: {
        slug: newSlug || slugify(newTitle),
        title: newTitle,
        topic_class: proposal.topic_class,
        topic_kind: newKind,
        description,
        aliases: [proposal.proposed_title, proposal.proposed_slug].filter(Boolean),
      },
    });
  };

  return (
    <div className="border border-white/10 rounded-2xl p-4 bg-slate-950/30 backdrop-blur-sm space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="font-medium text-cyan-200">{proposal.proposed_title}</h4>
            <span className="px-2 py-0.5 rounded-full bg-cyan-400/10 text-cyan-200 text-xs border border-cyan-300/20">
              {proposal.topic_class}
            </span>
            <span className="px-2 py-0.5 rounded-full bg-fuchsia-400/10 text-fuchsia-200 text-xs border border-fuchsia-300/20">
              {proposal.proposed_topic_kind}
            </span>
            <span className="px-2 py-0.5 rounded-full bg-white/10 text-slate-200 text-xs">
              {proposal.proposal_status}
            </span>
            {proposal.confidence !== null && (
              <span className="px-2 py-0.5 rounded-full bg-white/10 text-slate-200 text-xs">
                {(proposal.confidence * 100).toFixed(0)}% confidence
              </span>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1">slug: {proposal.proposed_slug}</p>
          {proposal.source_document_filename && (
            <p className="text-sm text-slate-300 mt-2">
              Source: {proposal.source_document_filename}
              {proposal.source_start_page !== null && proposal.source_end_page !== null
                ? ` · pages ${proposal.source_start_page}-${proposal.source_end_page}`
                : ''}
            </p>
          )}
          {proposal.description && <p className="text-sm text-slate-300 mt-2">{proposal.description}</p>}
          {proposal.rationale && (
            <div className="mt-3 p-3 bg-white/5 rounded-lg">
              <p className="text-xs text-slate-400 uppercase tracking-wide mb-1">Rationale</p>
              <p className="text-sm text-slate-300">{proposal.rationale}</p>
            </div>
          )}
        </div>
      </div>

      {proposal.proposal_status === 'proposed' && !expanded ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-sm text-slate-300">
            {proposal.matched_existing_topic_id
              ? 'Ha un possibile topic esistente: apri la review per confermare o cambiare target.'
              : 'Apri la review per creare un topic o collegarla a un topic esistente.'}
          </p>
          <button
            onClick={onToggleExpanded}
            className="rounded-full border border-cyan-300/25 bg-cyan-400/15 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-400/25"
          >
            Rivedi proposta
          </button>
        </div>
      ) : proposal.proposal_status === 'proposed' ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_15rem]">
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {[
                ['merge_into_existing', 'Unisci con esistente'],
                ['approve_new_topic', 'Crea topic canonico'],
                ['add_secondary_topic', 'Aggiungi come secondario'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setMode(value as typeof mode)}
                  className={`px-3 py-1.5 rounded-full text-sm border ${
                    mode === value
                      ? 'bg-cyan-400/20 text-cyan-100 border-cyan-300/40'
                      : 'bg-white/5 text-slate-300 border-white/10'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <div>
              <label className="text-xs uppercase tracking-wide text-slate-400">Assignment role</label>
              <select
                value={assignmentRole}
                onChange={(event) => setAssignmentRole(event.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
              >
                {ASSIGNMENT_ROLES.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>

            {mode === 'approve_new_topic' ? (
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="text-xs uppercase tracking-wide text-slate-400">Title</label>
                  <input
                    value={newTitle}
                    onChange={(event) => {
                      setNewTitle(event.target.value);
                      setNewSlug(slugify(event.target.value));
                    }}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-wide text-slate-400">Slug</label>
                  <input
                    value={newSlug}
                    onChange={(event) => setNewSlug(slugify(event.target.value))}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-wide text-slate-400">Topic kind</label>
                  <select
                    value={newKind}
                    onChange={(event) => setNewKind(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
                  >
                    {TOPIC_KINDS.map((kind) => (
                      <option key={kind} value={kind}>
                        {kind}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs uppercase tracking-wide text-slate-400">Description</label>
                  <textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 min-h-[88px]"
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <label className="text-xs uppercase tracking-wide text-slate-400">Target topic</label>
                <input
                  value={topicSearch}
                  onChange={(event) => setTopicSearch(event.target.value)}
                  placeholder="Filtra topic esistenti"
                  className="w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
                />
                <select
                  value={selectedTopicId}
                  onChange={(event) => setSelectedTopicId(event.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
                >
                  <option value="">
                    {filteredTopicOptions.length > 0
                      ? 'Seleziona un topic esistente'
                      : 'Nessun topic corrispondente'}
                  </option>
                  {filteredTopicOptions.map((topic) => (
                    <option key={topic.id} value={topic.id}>
                      {topic.title}
                      {` · ${topic.topic_kind} · ${topic.topic_class}`}
                      {!topic.is_active ? ' · inattivo' : ''}
                      {!topic.canonical ? ' · provvisorio' : ''}
                    </option>
                  ))}
                </select>
                {selectedTopic && (
                  <div className="rounded-xl border border-cyan-300/20 bg-cyan-400/10 px-3 py-2 text-sm text-cyan-100">
                    <div className="font-medium">{selectedTopic.title}</div>
                    <div className="mt-1 text-xs text-cyan-100/70">
                      {selectedTopic.topic_kind} · {selectedTopic.topic_class}
                      {!selectedTopic.is_active ? ' · inattivo' : ''}
                      {!selectedTopic.canonical ? ' · provvisorio' : ''}
                    </div>
                  </div>
                )}
                {topicOptions.length > TOPIC_OPTION_LIMIT && !topicSearch.trim() && (
                  <p className="px-1 text-xs text-slate-500">
                    Mostro i primi {TOPIC_OPTION_LIMIT} topic ordinati. Filtra per titolo, slug, classe o tipo.
                  </p>
                )}
                {filteredTopicOptions.length === 0 && (
                  <p className="px-1 text-xs italic text-slate-500">
                    Nessun topic trovato. Cambia filtro o crea un nuovo topic canonico.
                  </p>
                )}
                {!targetTopicSelectionIsValid && (
                  <p className="text-xs text-amber-200">
                    Seleziona un topic esistente dalla lista: non è possibile applicare la review senza target.
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <button
              onClick={onToggleExpanded}
              className="px-3 py-2 rounded-full bg-white/5 text-slate-200 text-sm font-medium border border-white/10 hover:bg-white/10"
            >
              Chiudi dettaglio
            </button>
            <button
              onClick={handleApprove}
              disabled={busy || !targetTopicSelectionIsValid}
              className="px-3 py-2 rounded-full bg-emerald-400/15 text-emerald-200 text-sm font-medium border border-emerald-300/25 hover:bg-emerald-400/25 disabled:opacity-50"
            >
              Apply review
            </button>
            {confirmReject ? (
              <button
                onClick={() => {
                  onReject(proposal.id);
                  setConfirmReject(false);
                }}
                disabled={busy}
                className="px-3 py-2 rounded-full bg-red-400/25 text-red-200 text-sm font-medium border border-red-300/35 hover:bg-red-400/35 disabled:opacity-50"
              >
                Confirm reject
              </button>
            ) : (
              <button
                onClick={() => setConfirmReject(true)}
                disabled={busy}
                className="px-3 py-2 rounded-full bg-red-400/10 text-red-200 text-sm font-medium border border-red-300/25 hover:bg-red-400/20 disabled:opacity-50"
              >
                Reject
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          disabled
          className="px-3 py-1.5 rounded-full bg-white/10 text-slate-400 text-sm font-medium border border-white/10 cursor-not-allowed"
        >
          Already consolidated
        </button>
      )}
    </div>
  );
});

function ProposalList({ onClose, initialProposals }: Props) {
  const [includeConsolidated, setIncludeConsolidated] = useState(false);
  const [expandedProposalId, setExpandedProposalId] = useState<string | null>(null);
  const shouldFetchProposals = includeConsolidated || !initialProposals;
  const proposalsQuery = useTopicProposals(includeConsolidated, shouldFetchProposals);
  const proposals = !includeConsolidated && initialProposals ? initialProposals : proposalsQuery.data;
  const isLoading = proposalsQuery.isLoading && !proposals;
  const error = proposalsQuery.error;
  const { data: topics = [] } = useKnowledgeTopics(true);
  const approve = useApproveTopicProposal();
  const reject = useRejectTopicProposal();

  const topicOptions = useMemo(() => {
    return [...topics].sort((left, right) => {
      const leftRank = (left.is_active ? 2 : 0) + (left.canonical ? 1 : 0);
      const rightRank = (right.is_active ? 2 : 0) + (right.canonical ? 1 : 0);
      if (leftRank !== rightRank) {
        return rightRank - leftRank;
      }
      return left.title.localeCompare(right.title, 'it');
    });
  }, [topics]);

  const toggleExpandedProposal = (proposalId: string) => {
    setExpandedProposalId((current) => (current === proposalId ? null : proposalId));
  };

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-1/3"></div>
        <div className="space-y-3">
          <div className="h-24 bg-gray-200 rounded"></div>
          <div className="h-24 bg-gray-200 rounded"></div>
          <div className="h-24 bg-gray-200 rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-lg">
        Error loading proposals: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Topic Proposals</h3>
          <p className="text-sm text-slate-400">
            Rivedi le proposte come assegnazioni multi-topic, non come una singola classificazione forzata.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm text-slate-300 flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeConsolidated}
              onChange={(event) => setIncludeConsolidated(event.target.checked)}
              className="rounded border-white/20 bg-slate-900 text-cyan-400 focus:ring-cyan-400"
            />
            Show consolidated
          </label>
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-full bg-white/10 text-slate-200 text-sm hover:bg-white/20"
          >
            Close
          </button>
        </div>
      </div>

      {proposals?.length === 0 ? (
        <div className="p-8 text-center bg-white/5 border border-white/10 rounded-2xl">
          <p className="text-slate-400">
            {includeConsolidated ? 'Nessuna proposta in questa vista.' : 'Nessuna proposta pendente.'}
          </p>
        </div>
      ) : (
        <div className="bg-white/5 border border-white/10 rounded-[24px] overflow-hidden backdrop-blur-md">
          <Virtuoso
            style={{ height: 'min(70vh, 600px)' }}
            totalCount={proposals?.length ?? 0}
            itemContent={(index) => {
              const proposal = proposals![index];
              return (
                <div className="p-4 border-b border-white/10 last:border-b-0">
                  <ProposalCard
                    proposal={proposal}
                    topicOptions={topicOptions}
                    onApprove={(proposalId, payload) => approve.mutate({ proposalId, payload })}
                    onReject={(proposalId) => reject.mutate(proposalId)}
                    busy={approve.isPending || reject.isPending}
                    expanded={expandedProposalId === proposal.id}
                    onToggleExpanded={() => toggleExpandedProposal(proposal.id)}
                  />
                </div>
              );
            }}
            increaseViewportBy={{ top: 200, bottom: 200 }}
          />
        </div>
      )}
    </div>
  );
}

export default ProposalList;
