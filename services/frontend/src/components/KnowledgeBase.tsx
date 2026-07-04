import { useDeferredValue, useState } from 'react';
import {
  useKnowledgeGraphStats,
  useKnowledgeTopics,
  useTopicProposals,
} from '../hooks/useDocuments';
import ProposalList from './ProposalList';
import {
  FactsPanel,
  SpecialistsPanel,
  TopicsPanel,
  EntitiesPanel,
  ReviewsPanel,
  AgentPanel,
} from './KnowledgeBasePanels';
import { TopicCleanupPanel } from './TopicCleanupPanel';

interface Props {
  onOpenDocument: (documentId: string) => void;
}

type Panel = 'agent' | 'facts' | 'specialists' | 'topics' | 'entities' | 'reviews' | 'cleanup';

function KnowledgeBase({ onOpenDocument }: Props) {
  const [panel, setPanel] = useState<Panel>('facts');
  const [searchInput, setSearchInput] = useState('');
  const [showProposals, setShowProposals] = useState(false);
  const [isSideNavCollapsed, setIsSideNavCollapsed] = useState(() => {
    return window.localStorage.getItem('megadoc.knowledgeNavCollapsed') === 'true';
  });
  const deferredSearch = useDeferredValue(searchInput.trim());

  const topicsQuery = useKnowledgeTopics(false);
  const topics = topicsQuery.data ?? [];
  const graphStats = useKnowledgeGraphStats();
  const proposals = useTopicProposals();

  const tabClass = (current: boolean) =>
    `rounded-full border px-4 py-2 text-sm transition lg:w-full lg:rounded-xl ${
      isSideNavCollapsed ? 'lg:px-2 lg:text-center' : 'lg:text-left'
    } ${
      current
        ? 'border-cyan-300/50 bg-gradient-to-r from-cyan-400/20 to-indigo-400/20 text-cyan-100 shadow-lg shadow-cyan-950/20'
        : 'border-white/10 bg-white/5 text-slate-300 hover:border-cyan-300/25 hover:bg-cyan-300/10 hover:text-white'
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
    <div
      className={`grid h-[calc(100vh-7.75rem)] min-h-[38rem] gap-3 lg:h-[calc(100vh-2rem)] ${
        isSideNavCollapsed ? 'lg:grid-cols-[4.75rem_minmax(0,1fr)]' : 'lg:grid-cols-[18rem_minmax(0,1fr)]'
      } lg:transition-[grid-template-columns] lg:duration-200`}
    >
      <aside className="flex min-h-0 flex-col rounded-lg border border-cyan-300/15 bg-slate-900/85 p-4 shadow-2xl shadow-cyan-950/20">
        <div className={`flex shrink-0 flex-wrap items-center gap-3 ${isSideNavCollapsed ? 'lg:justify-center' : 'lg:block'}`}>
          <button
            type="button"
            onClick={() => {
              const next = !isSideNavCollapsed;
              setIsSideNavCollapsed(next);
              window.localStorage.setItem('megadoc.knowledgeNavCollapsed', String(next));
            }}
            title={isSideNavCollapsed ? 'Espandi menu conoscenza' : 'Collassa menu conoscenza'}
            className="hidden rounded-xl border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-2 text-sm text-cyan-100 transition hover:bg-cyan-300/20 lg:block"
          >
            {isSideNavCollapsed ? '»' : '«'}
          </button>
          <div className={`flex min-w-[16rem] flex-1 items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-2.5 lg:min-w-0 ${isSideNavCollapsed ? 'lg:hidden' : ''}`}>
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
          <div className={`flex flex-wrap gap-2 text-xs lg:mt-3 lg:grid lg:grid-cols-2 ${isSideNavCollapsed ? 'lg:hidden' : ''}`}>
            <span className="rounded-full border border-indigo-300/20 bg-indigo-400/10 px-3 py-2 text-indigo-100">
              {graphStats.data?.nodes ?? 0} nodi
            </span>
            <span className="rounded-full border border-emerald-300/20 bg-emerald-400/10 px-3 py-2 text-emerald-100">
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
        <nav className="mt-3 flex shrink-0 flex-wrap gap-2 lg:min-h-0 lg:flex-1 lg:flex-col lg:overflow-y-auto">
          {[
            { id: 'facts' as Panel, label: 'Fatti', short: 'F' },
            { id: 'agent' as Panel, label: 'Dialogo', short: 'D' },
            { id: 'specialists' as Panel, label: 'Specialisti', short: 'S' },
            { id: 'topics' as Panel, label: 'Topic', short: 'T' },
            { id: 'entities' as Panel, label: 'Entità', short: 'E' },
            { id: 'reviews' as Panel, label: 'Revisioni', short: 'R' },
            { id: 'cleanup' as Panel, label: 'Cleanup', short: 'C' },
          ].map((tab) => (
            <button key={tab.id} onClick={() => setPanel(tab.id)} title={tab.label} className={tabClass(panel === tab.id)}>
              <span className={isSideNavCollapsed ? 'hidden lg:inline' : 'hidden'}>{tab.short}</span>
              <span className={isSideNavCollapsed ? 'lg:hidden' : ''}>{tab.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="min-h-0 overflow-hidden rounded-lg border border-cyan-300/15 bg-slate-900/85 p-3 shadow-2xl shadow-cyan-950/20 lg:p-4">
        {panel === 'facts' && <FactsPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} />}
        {panel === 'agent' && <AgentPanel onOpenDocument={onOpenDocument} />}
        {panel === 'specialists' && <SpecialistsPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} />}
        {panel === 'topics' && <TopicsPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} includeInactive={false} />}
        {panel === 'entities' && <EntitiesPanel onOpenDocument={onOpenDocument} deferredSearch={deferredSearch} />}
        {panel === 'reviews' && <ReviewsPanel deferredSearch={deferredSearch} />}
        {panel === 'cleanup' && <TopicCleanupPanel deferredSearch={deferredSearch} />}
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
