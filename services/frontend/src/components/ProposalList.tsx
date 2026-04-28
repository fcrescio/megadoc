import { useState } from 'react';
import {
  useTopicProposals,
  useApproveTopicProposal,
  useRejectTopicProposal,
} from '../hooks/useDocuments';

interface Props {
  onClose: () => void;
}

function ProposalList({ onClose }: Props) {
  const [includeConsolidated, setIncludeConsolidated] = useState(false);
  const { data: proposals, isLoading, error } = useTopicProposals(includeConsolidated);
  const approve = useApproveTopicProposal();
  const reject = useRejectTopicProposal();

  const [confirmId, setConfirmId] = useState<string | null>(null);

  const handleApprove = (proposalId: string) => {
    approve.mutate(proposalId);
  };

  const handleReject = (proposalId: string) => {
    reject.mutate(proposalId);
  };

  const handleConfirmReject = (proposalId: string) => {
    if (confirmId === proposalId) {
      handleReject(proposalId);
      setConfirmId(null);
    } else {
      setConfirmId(proposalId);
    }
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
            Review only pending proposals. Consolidated items can be inspected separately.
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
            <div
              key={proposal.id}
              className="border border-white/10 rounded-2xl p-4 bg-slate-950/30 backdrop-blur-sm"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h4 className="font-medium text-cyan-200">{proposal.proposed_title}</h4>
                    <span className="px-2 py-0.5 rounded-full bg-cyan-400/10 text-cyan-200 text-xs border border-cyan-300/20">
                      {proposal.topic_class}
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
                  {proposal.matched_existing_topic_title && (
                    <p className="text-sm text-slate-300 mt-2">
                      Current matched topic: {proposal.matched_existing_topic_title}
                    </p>
                  )}
                  {proposal.source_document_filename && (
                    <p className="text-sm text-slate-300 mt-2">
                      Source: {proposal.source_document_filename}
                      {proposal.source_start_page !== null && proposal.source_end_page !== null
                        ? ` · pages ${proposal.source_start_page}-${proposal.source_end_page}`
                        : ''}
                    </p>
                  )}
                  {proposal.description && (
                    <p className="text-sm text-slate-300 mt-2">{proposal.description}</p>
                  )}
                  {proposal.rationale && (
                    <div className="mt-3 p-3 bg-white/5 rounded-lg">
                      <p className="text-xs text-slate-400 uppercase tracking-wide mb-1">Rationale</p>
                      <p className="text-sm text-slate-300">{proposal.rationale}</p>
                    </div>
                  )}
                  <p className="text-xs text-slate-500 mt-3">
                    Created {new Date(proposal.created_at).toLocaleString()}
                  </p>
                </div>

                <div className="flex flex-col gap-2 shrink-0">
                  {proposal.proposal_status === 'proposed' ? (
                    <>
                      <button
                        onClick={() => handleApprove(proposal.id)}
                        disabled={approve.isPending || reject.isPending}
                        className="px-3 py-1.5 rounded-full bg-emerald-400/15 text-emerald-200 text-sm font-medium border border-emerald-300/25 hover:bg-emerald-400/25 disabled:opacity-50"
                      >
                        {approve.isPending && approve.variables === proposal.id ? 'Approving...' : 'Approve'}
                      </button>
                      {confirmId === proposal.id ? (
                        <button
                          onClick={() => {
                            handleReject(proposal.id);
                            setConfirmId(null);
                          }}
                          disabled={approve.isPending || reject.isPending}
                          className="px-3 py-1.5 rounded-full bg-red-400/25 text-red-200 text-sm font-medium border border-red-300/35 hover:bg-red-400/35 disabled:opacity-50"
                        >
                          {reject.isPending && reject.variables === proposal.id ? 'Rejecting...' : 'Confirm Reject'}
                        </button>
                      ) : (
                        <button
                          onClick={() => handleConfirmReject(proposal.id)}
                          disabled={approve.isPending || reject.isPending}
                          className="px-3 py-1.5 rounded-full bg-red-400/10 text-red-200 text-sm font-medium border border-red-300/25 hover:bg-red-400/20 disabled:opacity-50"
                        >
                          Reject
                        </button>
                      )}
                    </>
                  ) : (
                    <button
                      disabled
                      className="px-3 py-1.5 rounded-full bg-white/10 text-slate-400 text-sm font-medium border border-white/10 cursor-not-allowed"
                    >
                      Already consolidated
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ProposalList;
