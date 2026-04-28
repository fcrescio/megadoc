import { useMemo, useState } from 'react';
import {
  useApproveTopicProposal,
  useKnowledgeTopics,
  useRejectTopicProposal,
  useTopicProposals,
} from '../hooks/useDocuments';
import type { KnowledgeTopicProposal, KnowledgeTopicSummary, TopicCreatePayload } from '../types';

interface Props {
  onClose: () => void;
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

function ProposalCard({
  proposal,
  topics,
  onApprove,
  onReject,
  busy,
}: {
  proposal: KnowledgeTopicProposal;
  topics: KnowledgeTopicSummary[];
  onApprove: (proposalId: string, payload: {
    action: 'approve_new_topic' | 'merge_into_existing' | 'add_secondary_topic';
    assignment_role: string;
    target_topic_id?: string;
    create_topic?: TopicCreatePayload;
  }) => void;
  onReject: (proposalId: string) => void;
  busy: boolean;
}) {
  const [mode, setMode] = useState<'merge_into_existing' | 'approve_new_topic' | 'add_secondary_topic'>(
    proposal.matched_existing_topic_id ? 'merge_into_existing' : 'approve_new_topic',
  );
  const [assignmentRole, setAssignmentRole] = useState('subject');
  const [topicSearch, setTopicSearch] = useState(proposal.matched_existing_topic_title ?? '');
  const [selectedTopicId, setSelectedTopicId] = useState<string>(proposal.matched_existing_topic_id ?? '');
  const [newTitle, setNewTitle] = useState(proposal.proposed_title);
  const [newSlug, setNewSlug] = useState(proposal.proposed_slug);
  const [newKind, setNewKind] = useState(proposal.proposed_topic_kind);
  const [description, setDescription] = useState(proposal.description ?? '');
  const [confirmReject, setConfirmReject] = useState(false);

  const filteredTopics = useMemo(() => {
    const query = topicSearch.trim().toLowerCase();
    const source = topics.filter((topic) => topic.is_active);
    if (!query) {
      return source.slice(0, 8);
    }
    return source
      .filter((topic) =>
        [topic.title, topic.slug, topic.topic_class, topic.topic_kind].join(' ').toLowerCase().includes(query),
      )
      .slice(0, 8);
  }, [topicSearch, topics]);

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

      {proposal.proposal_status === 'proposed' ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_15rem]">
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {[
                ['merge_into_existing', 'Merge into existing'],
                ['approve_new_topic', 'Create canonical topic'],
                ['add_secondary_topic', 'Add as secondary'],
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
                  placeholder="Search existing topics"
                  className="w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
                />
                <div className="grid gap-2 max-h-44 overflow-y-auto">
                  {filteredTopics.map((topic) => (
                    <button
                      key={topic.id}
                      onClick={() => {
                        setSelectedTopicId(topic.id);
                        setTopicSearch(topic.title);
                      }}
                      className={`text-left rounded-xl border px-3 py-2 ${
                        selectedTopicId === topic.id
                          ? 'border-cyan-300/40 bg-cyan-400/10 text-cyan-100'
                          : 'border-white/10 bg-white/5 text-slate-200'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium">{topic.title}</span>
                        <span className="text-xs text-slate-400">
                          {topic.topic_kind} · {topic.topic_class}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <button
              onClick={handleApprove}
              disabled={busy}
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
}

function ProposalList({ onClose }: Props) {
  const [includeConsolidated, setIncludeConsolidated] = useState(false);
  const { data: proposals, isLoading, error } = useTopicProposals(includeConsolidated);
  const { data: topics = [] } = useKnowledgeTopics(true);
  const approve = useApproveTopicProposal();
  const reject = useRejectTopicProposal();

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
            Review proposals as multi-topic assignments, not as a single forced classification.
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
            {includeConsolidated ? 'No proposals in this view.' : 'No pending proposals.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {proposals?.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              topics={topics}
              onApprove={(proposalId, payload) => approve.mutate({ proposalId, payload })}
              onReject={(proposalId) => reject.mutate(proposalId)}
              busy={approve.isPending || reject.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default ProposalList;
