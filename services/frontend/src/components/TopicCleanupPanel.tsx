import { memo, useState } from 'react';
import { useKnowledgeTopics, useMergeTopic } from '../hooks/useDocuments';
import type { KnowledgeTopicSummary } from '../types';

interface CleanupCandidate {
  category: string;
  note: string;
  topic_id?: string;
  title?: string;
  slug?: string;
  topic_kind?: string;
  topic_class?: string;
  assignment_count?: number;
  candidates?: Array<{
    topic_id: string;
    title: string;
    slug: string;
    topic_kind: string;
  }>;
  typo_candidate?: {
    topic_id: string;
    title: string;
    slug: string;
    assignment_count: number;
  };
  canonical_candidate?: {
    topic_id: string;
    title: string;
    slug: string;
    assignment_count: number;
  };
  current_kind?: string;
  dominant_family?: string;
  expected_kind?: string;
  axis?: string;
}

interface Props {
  deferredSearch: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  near_orphan: 'Quasi orfani',
  duplicate_title: 'Titoli duplicati',
  shared_identity_axis: 'Assi identità condivisi',
  probable_typo: 'Possibili typo',
  kind_mismatch: 'Kind incompatibile',
};

const CATEGORY_COLORS: Record<string, string> = {
  near_orphan: 'border-slate-500/30 bg-slate-500/10',
  duplicate_title: 'border-amber-500/30 bg-amber-500/10',
  shared_identity_axis: 'border-cyan-500/30 bg-cyan-500/10',
  probable_typo: 'border-rose-500/30 bg-rose-500/10',
  kind_mismatch: 'border-fuchsia-500/30 bg-fuchsia-500/10',
};

export const TopicCleanupPanel = memo(function TopicCleanupPanel({ deferredSearch: _deferredSearch }: Props) {
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [mergeTargets, setMergeTargets] = useState<Record<string, string>>({});
  const [mergeNotes, setMergeNotes] = useState<Record<string, string>>({});
  const [mergeAuthor, setMergeAuthor] = useState('');
  const [mergeResults, setMergeResults] = useState<Record<string, string>>({});

  const topicsQuery = useKnowledgeTopics(true);
  const mergeMutation = useMergeTopic();

  const topics = topicsQuery.data ?? [];

  // Build cleanup candidates from topics data
  const candidates = buildCandidates(topics);

  const categories = Object.keys(CATEGORY_LABELS).filter(
    (cat) => candidates[cat] && candidates[cat].length > 0
  );

  const handleMerge = async (sourceId: string, targetId: string, note: string) => {
    const key = `${sourceId}->${targetId}`;
    try {
      const result = await mergeMutation.mutateAsync({
        sourceId,
        payload: {
          target_topic_id: targetId,
          acted_by: mergeAuthor || null,
          note: note || null,
        },
      });
      setMergeResults((prev) => ({ ...prev, [key]: `Fatto: ${result.affected_assignments} assegnazioni spostate, ${result.aliases_created} alias creati` }));
    } catch (err) {
      setMergeResults((prev) => ({ ...prev, [key]: `Errore: ${(err as Error).message}` }));
    }
  };

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Author input */}
      <div className="flex shrink-0 items-center gap-3">
        <input
          value={mergeAuthor}
          onChange={(e) => setMergeAuthor(e.target.value)}
          placeholder="Operatore (facoltativo)"
          className="rounded-xl border border-white/10 bg-slate-950/50 px-3 py-2 text-sm"
        />
        <span className="text-xs text-slate-400">
          {topics.length} topic attivi · {categories.length} categorie
        </span>
      </div>

      {/* Category tabs */}
      <nav className="flex shrink-0 flex-wrap gap-2">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
            className={`rounded-full border px-3 py-1.5 text-xs ${
              activeCategory === cat
                ? 'border-cyan-300/35 bg-cyan-400/15 text-cyan-100'
                : CATEGORY_COLORS[cat] + ' text-slate-200'
            }`}
          >
            {CATEGORY_LABELS[cat]} ({candidates[cat].length})
          </button>
        ))}
        {categories.length === 0 && (
          <p className="text-sm text-slate-400">Nessun candidato trovato. Esegui il report script per dati aggiornati.</p>
        )}
      </nav>

      {/* Candidates list */}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
        {categories
          .filter((cat) => !activeCategory || cat === activeCategory)
          .map((cat) => (
            <div key={cat}>
              {!activeCategory && (
                <h3 className="mb-2 text-sm font-semibold text-white">{CATEGORY_LABELS[cat]}</h3>
              )}
              <div className="space-y-2">
                {candidates[cat].map((item: CleanupCandidate, idx: number) => (
                  <CandidateCard
                    key={`${cat}-${idx}`}
                    item={item}
                    category={cat}
                    topics={topics}
                    mergeTargets={mergeTargets}
                    mergeNotes={mergeNotes}
                    mergeResults={mergeResults}
                    onMergeTargetChange={(sourceId, targetId) =>
                      setMergeTargets((prev) => ({ ...prev, [sourceId]: targetId }))
                    }
                    onMergeNoteChange={(key, note) =>
                      setMergeNotes((prev) => ({ ...prev, [key]: note }))
                    }
                    onMerge={handleMerge}
                    isMerging={mergeMutation.isPending}
                  />
                ))}
              </div>
            </div>
          ))}
      </div>
    </div>
  );
});

/* ── Candidate Card ── */

interface CandidateCardProps {
  item: CleanupCandidate;
  category: string;
  topics: KnowledgeTopicSummary[];
  mergeTargets: Record<string, string>;
  mergeNotes: Record<string, string>;
  mergeResults: Record<string, string>;
  onMergeTargetChange: (sourceId: string, targetId: string) => void;
  onMergeNoteChange: (key: string, note: string) => void;
  onMerge: (sourceId: string, targetId: string, note: string) => void;
  isMerging: boolean;
}

const CandidateCard = memo(function CandidateCard({
  item,
  category,
  topics,
  mergeTargets,
  mergeNotes,
  mergeResults,
  onMergeTargetChange,
  onMergeNoteChange,
  onMerge,
  isMerging,
}: CandidateCardProps) {
  if (category === 'near_orphan') {
    return (
      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-white">{item.title}</p>
            <p className="text-xs text-slate-400">{item.slug} · {item.topic_kind} · {item.assignment_count} assegnazioni</p>
            <p className="mt-1 text-xs text-slate-500">{item.note}</p>
          </div>
          <MergeForm
            sourceId={item.topic_id!}
            topics={topics}
            mergeTargets={mergeTargets}
            mergeNotes={mergeNotes}
            mergeResults={mergeResults}
            onMergeTargetChange={onMergeTargetChange}
            onMergeNoteChange={onMergeNoteChange}
            onMerge={onMerge}
            isMerging={isMerging}
          />
        </div>
      </div>
    );
  }

  if (category === 'duplicate_title' && item.candidates) {
    return (
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
        <p className="mb-2 text-xs text-amber-200">{item.note}</p>
        <div className="space-y-2">
          {item.candidates.map((c) => (
            <div key={c.topic_id} className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-white">{c.title}</p>
                <p className="text-xs text-slate-400">{c.slug} · {c.topic_kind}</p>
              </div>
              <MergeForm
                sourceId={c.topic_id}
                topics={topics}
                mergeTargets={mergeTargets}
                mergeNotes={mergeNotes}
                mergeResults={mergeResults}
                onMergeTargetChange={onMergeTargetChange}
                onMergeNoteChange={onMergeNoteChange}
                onMerge={onMerge}
                isMerging={isMerging}
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (category === 'shared_identity_axis' && item.candidates) {
    return (
      <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3">
        <p className="mb-2 text-xs text-cyan-200">{item.note}</p>
        <p className="mb-2 text-xs text-slate-500">Asse: {item.axis}</p>
        <div className="space-y-2">
          {item.candidates.map((c) => (
            <div key={c.topic_id} className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-white">{c.title}</p>
                <p className="text-xs text-slate-400">{c.slug} · {c.topic_kind}</p>
              </div>
              <MergeForm
                sourceId={c.topic_id}
                topics={topics}
                mergeTargets={mergeTargets}
                mergeNotes={mergeNotes}
                mergeResults={mergeResults}
                onMergeTargetChange={onMergeTargetChange}
                onMergeNoteChange={onMergeNoteChange}
                onMerge={onMerge}
                isMerging={isMerging}
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (category === 'probable_typo') {
    return (
      <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-3">
        <p className="mb-2 text-xs text-rose-200">{item.note}</p>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-rose-100 line-through">{item.typo_candidate?.title}</p>
            <p className="text-xs text-slate-400">{item.typo_candidate?.slug} · {item.typo_candidate?.assignment_count} assegnazioni</p>
            <p className="mt-2 text-sm text-emerald-100">→ {item.canonical_candidate?.title}</p>
            <p className="text-xs text-slate-400">{item.canonical_candidate?.slug} · {item.canonical_candidate?.assignment_count} assegnazioni</p>
          </div>
          <MergeForm
            sourceId={item.typo_candidate!.topic_id}
            topics={topics}
            mergeTargets={mergeTargets}
            mergeNotes={mergeNotes}
            mergeResults={mergeResults}
            onMergeTargetChange={onMergeTargetChange}
            onMergeNoteChange={onMergeNoteChange}
            onMerge={onMerge}
            isMerging={isMerging}
            defaultTargetId={item.canonical_candidate?.topic_id}
          />
        </div>
      </div>
    );
  }

  if (category === 'kind_mismatch') {
    return (
      <div className="rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/5 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-white">{item.title}</p>
            <p className="text-xs text-slate-400">{item.slug}</p>
            <p className="mt-1 text-xs text-fuchsia-200">
              kind attuale: <span className="line-through">{item.current_kind}</span> → atteso: {item.expected_kind}
            </p>
            <p className="text-xs text-slate-500">Famiglia dominante: {item.dominant_family}</p>
          </div>
        </div>
      </div>
    );
  }

  return null;
});

/* ── Merge Form ── */

interface MergeFormProps {
  sourceId: string;
  topics: KnowledgeTopicSummary[];
  mergeTargets: Record<string, string>;
  mergeNotes: Record<string, string>;
  mergeResults: Record<string, string>;
  onMergeTargetChange: (sourceId: string, targetId: string) => void;
  onMergeNoteChange: (key: string, note: string) => void;
  onMerge: (sourceId: string, targetId: string, note: string) => void;
  isMerging: boolean;
  defaultTargetId?: string;
}

const MergeForm = memo(function MergeForm({
  sourceId,
  topics,
  mergeTargets,
  mergeNotes,
  mergeResults,
  onMergeTargetChange,
  onMergeNoteChange,
  onMerge,
  isMerging,
  defaultTargetId,
}: MergeFormProps) {
  const targetId = mergeTargets[sourceId] ?? defaultTargetId ?? '';
  const noteKey = `note-${sourceId}`;
  const resultKey = `${sourceId}->${targetId}`;
  const result = mergeResults[resultKey];

  return (
    <div className="flex shrink-0 flex-col gap-2">
      <select
        value={targetId}
        onChange={(e) => onMergeTargetChange(sourceId, e.target.value)}
        className="max-w-[14rem] rounded-lg border border-white/10 bg-slate-950/60 px-2 py-1.5 text-xs"
      >
        <option value="">— Unisci in —</option>
        {topics
          .filter((t) => t.id !== sourceId && t.is_active)
          .map((t) => (
            <option key={t.id} value={t.id}>
              {t.title.slice(0, 50)}
            </option>
          ))}
      </select>
      <input
        value={mergeNotes[noteKey] ?? ''}
        onChange={(e) => onMergeNoteChange(noteKey, e.target.value)}
        placeholder="Nota"
        className="rounded-lg border border-white/10 bg-slate-950/60 px-2 py-1.5 text-xs"
      />
      {targetId && (
        <button
          onClick={() => onMerge(sourceId, targetId, mergeNotes[noteKey] ?? '')}
          disabled={isMerging}
          className="rounded-lg border border-emerald-300/25 bg-emerald-400/15 px-3 py-1.5 text-xs text-emerald-100 disabled:opacity-50"
        >
          {isMerging ? 'Unendo...' : 'Unisci'}
        </button>
      )}
      {result && (
        <p className={`text-xs ${result.startsWith('Errore') ? 'text-rose-300' : 'text-emerald-300'}`}>
          {result}
        </p>
      )}
    </div>
  );
});

/* ── Candidate builder ── */

function buildCandidates(topics: KnowledgeTopicSummary[]): Record<string, CleanupCandidate[]> {
  const result: Record<string, CleanupCandidate[]> = {
    near_orphan: [],
    duplicate_title: [],
    shared_identity_axis: [],
    probable_typo: [],
    kind_mismatch: [],
  };

  // Near orphans: topics with 0 or 1 assignments
  for (const t of topics) {
    const count = t.assignment_count ?? 0;
    if (count <= 1) {
      result.near_orphan.push({
        category: 'near_orphan',
        topic_id: t.id,
        title: t.title,
        slug: t.slug,
        topic_kind: t.topic_kind,
        topic_class: t.topic_class,
        assignment_count: count,
        note: count === 0 ? 'Nessuna assegnazione' : 'Solo 1 assegnazione',
      });
    }
  }

  // Note: duplicate_title, shared_identity_axis, probable_typo, kind_mismatch
  // require DB-level analysis (archive_identity, document_family) that the
  // frontend doesn't have. These are best computed server-side via the report script.
  // The frontend panel focuses on the merge action UI for near-orphans.
  // For a full experience, the report JSON can be loaded via an API endpoint.

  return result;
}
