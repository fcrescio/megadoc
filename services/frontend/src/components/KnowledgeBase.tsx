import { useDeferredValue, useState } from 'react';
import {
  useKnowledgeGraphStats,
  useKnowledgeTopics,
  useTopicProposals,
} from '../hooks/useDocuments';
import ProposalList from './ProposalList';
import {
  ComparisonsPanel,
  FactsPanel,
  SpecialistsPanel,
  TopicsPanel,
  EntitiesPanel,
  ReviewsPanel,
} from './KnowledgeBasePanels';

interface Props {
  onOpenDocument: (documentId: string) => void;
}

type Panel = 'comparisons' | 'facts' | 'specialists' | 'topics' | 'entities' | 'reviews';

function KnowledgeBase({ onOpenDocument }: Props) {
  const [panel, setPanel] = useState<Panel>('comparisons');
  const [searchInput, setSearchInput] = useState('');
  const [showProposals, setShowProposals] = useState(false);
  const deferredSearch = useDeferredValue(searchInput.trim());

  const topicsQuery = useKnowledgeTopics(false);
  const topics = topicsQuery.data ?? [];
  const graphStats = useKnowledgeGraphStats();
  const proposals = useTopicProposals();

  const tabClass = (current: boolean) =>
    `rounded-full border px-4 py-2 text-sm transition ${
      current
        ? 'border-cyan-300/35 bg-cyan-400/15 text-cyan-100'
        : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
    }`;

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

  return (
    <div className="flex h-[calc(100vh-7.75rem)] min-h-[38rem] flex-col gap-3">
      <section className="shrink-0 rounded-lg border border-slate-700 bg-slate-800 p-4">
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
            { id: 'reviews' as Panel, label: 'Revisioni' },
          ].map((tab) => (
            <button key={tab.id} onClick={() => setPanel(tab.id)} className={tabClass(panel === tab.id)}>
              {tab.label}
            </button>
          ))}
        </nav>
      </section>

      <section className="min-h-0 flex-1 overflow-hidden rounded-lg border border-slate-700 bg-slate-800 p-4">
        {panel === 'comparisons' && <ComparisonsPanel onOpenDocument={onOpenDocument} />}
        {panel === 'facts' && <FactsPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} />}
        {panel === 'specialists' && <SpecialistsPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} />}
        {panel === 'topics' && <TopicsPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} includeInactive={false} />}
        {panel === 'entities' && <EntitiesPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} />}
        {panel === 'reviews' && <ReviewsPanel deferredSearch={deferredSearch} />}
      </section>

      {showProposals && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/75 p-4" onClick={() => setShowProposals(false)}>
          <div className="max-h-[88vh] w-full max-w-5xl overflow-y-auto rounded-3xl border border-amber-300/20 bg-slate-900 p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <ProposalList
              initialProposals={proposals.data}
              onClose={() => setShowProposals(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default KnowledgeBase;
