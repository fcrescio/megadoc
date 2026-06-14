import { useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useCreateManualComment, useManual, useUpdateManualComment } from '../hooks/useDocuments';

interface TextSelectionState {
  text: string;
  start: number | null;
  end: number | null;
}

function getSelectionOffsets(container: HTMLElement): TextSelectionState | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return null;
  }
  const range = selection.getRangeAt(0);
  if (!container.contains(range.commonAncestorContainer)) {
    return null;
  }
  const text = selection.toString().trim();
  if (text.length < 3) {
    return null;
  }

  const preRange = range.cloneRange();
  preRange.selectNodeContents(container);
  preRange.setEnd(range.startContainer, range.startOffset);
  const start = preRange.toString().length;
  const end = start + selection.toString().length;

  return { text, start, end };
}

function ManualView() {
  const manual = useManual('system');
  const createComment = useCreateManualComment();
  const updateComment = useUpdateManualComment();
  const articleRef = useRef<HTMLDivElement | null>(null);
  const [selection, setSelection] = useState<TextSelectionState | null>(null);
  const [authorName, setAuthorName] = useState('');
  const [commentText, setCommentText] = useState('');
  const [resolutionAuthor, setResolutionAuthor] = useState('');
  const [resolutionNotes, setResolutionNotes] = useState<Record<string, string>>({});

  const handleArticleSelection = () => {
    if (!articleRef.current) {
      return;
    }
    const nextSelection = getSelectionOffsets(articleRef.current);
    if (nextSelection) {
      setSelection(nextSelection);
    }
  };

  const architectureComments = manual.data?.comments ?? [];
  const commentStats = useMemo(() => {
    return {
      total: architectureComments.length,
      open: architectureComments.filter((comment) => comment.status === 'open').length,
      commentedPassages: new Set(architectureComments.map((comment) => comment.selected_text)).size,
    };
  }, [architectureComments]);

  if (manual.isLoading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-10 w-2/5 rounded bg-white/10" />
        <div className="h-64 rounded-[28px] bg-white/5" />
      </div>
    );
  }

  if (manual.error || !manual.data) {
    return (
      <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 p-4 text-rose-100">
        Error loading manual: {(manual.error as Error)?.message ?? 'unknown error'}
      </div>
    );
  }

  const manualData = manual.data;

  const submitComment = () => {
    if (!selection || !commentText.trim()) {
      return;
    }
    createComment.mutate(
      {
        slug: manualData.slug,
        payload: {
          selected_text: selection.text,
          selection_start: selection.start,
          selection_end: selection.end,
          comment_text: commentText.trim(),
          author_name: authorName.trim() || null,
        },
      },
      {
        onSuccess: () => {
          setSelection(null);
          setCommentText('');
          setAuthorName('');
          window.getSelection()?.removeAllRanges();
        },
      },
    );
  };

  const submitResolution = (commentId: string, status: 'resolved' | 'wontfix') => {
    updateComment.mutate({
      slug: manualData.slug,
      commentId,
      payload: {
        status,
        resolution_note: resolutionNotes[commentId]?.trim() || null,
        resolved_by: resolutionAuthor.trim() || null,
      },
    });
  };

  const reopenComment = (commentId: string) => {
    updateComment.mutate({
      slug: manualData.slug,
      commentId,
      payload: {
        status: 'open',
      },
    });
  };

  const statusBadgeClass = (status: string) => {
    if (status === 'resolved') {
      return 'border-emerald-300/20 bg-emerald-400/15 text-emerald-100';
    }
    if (status === 'wontfix') {
      return 'border-amber-300/20 bg-amber-400/15 text-amber-100';
    }
    return 'border-cyan-300/20 bg-cyan-400/15 text-cyan-100';
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
        <div className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr] p-6 lg:p-8">
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-fuchsia-200/80 mb-3">Manuale Vivo</p>
            <h2 className="text-3xl lg:text-4xl font-semibold text-white">{manualData.title}</h2>
            <p className="text-sm text-slate-300 mt-3 max-w-2xl">
              Questo manuale fa parte del prodotto. Seleziona un passaggio, aggiungi un commento e migliora la
              descrizione del sistema in modo incrementale.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-fuchsia-300/15 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-wide text-fuchsia-200/70">Commenti</p>
              <p className="mt-2 text-2xl font-semibold text-white">{commentStats.total}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-wide text-fuchsia-200/70">Aperti</p>
              <p className="mt-2 text-2xl font-semibold text-white">{commentStats.open}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 col-span-2">
              <p className="text-xs uppercase tracking-wide text-fuchsia-200/70">Passaggi Annotati</p>
              <p className="mt-2 text-2xl font-semibold text-white">{commentStats.commentedPassages}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 col-span-2">
              <p className="text-xs uppercase tracking-wide text-fuchsia-200/70">Annotazione</p>
              <p className="mt-2 text-sm text-slate-200">
                Evidenzia una frase del manuale e lascia una nota. I commenti vengono salvati insieme al testo
                selezionato e servono a migliorare questo documento nel tempo.
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
          <div className="border-b border-white/10 px-6 py-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.28em] text-fuchsia-200/70">Testo di Riferimento</p>
              <h3 className="text-lg font-semibold text-white">Architettura, principi e review</h3>
            </div>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200">
              slug: {manualData.slug}
            </span>
          </div>
          <div
            ref={articleRef}
            onMouseUp={handleArticleSelection}
            onKeyUp={handleArticleSelection}
            className="markdown-body max-h-[78vh] overflow-y-auto px-6 py-6 selection:bg-fuchsia-400/35"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{manualData.markdown}</ReactMarkdown>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-fuchsia-200/70 mb-3">Passaggio Selezionato</p>
            {selection ? (
              <div className="space-y-3">
                <blockquote className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
                  {selection.text}
                </blockquote>
                <input
                  value={authorName}
                  onChange={(event) => setAuthorName(event.target.value)}
                  placeholder="Il tuo nome (opzionale)"
                  className="w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
                />
                <textarea
                  value={commentText}
                  onChange={(event) => setCommentText(event.target.value)}
                  placeholder="Aggiungi un commento, una correzione o una nota architetturale..."
                  className="w-full min-h-[8rem] rounded-2xl border border-white/10 bg-slate-900/70 px-3 py-3 text-sm text-slate-100 placeholder:text-slate-500"
                />
                {createComment.error && (
                  <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
                    Errore salvataggio commento: {createComment.error.message}
                  </div>
                )}
                <div className="flex items-center gap-3">
                  <button
                    onClick={submitComment}
                    disabled={createComment.isPending || !commentText.trim()}
                    className="rounded-full border border-fuchsia-300/25 bg-fuchsia-400/20 px-4 py-2 text-sm text-fuchsia-50 hover:bg-fuchsia-400/25 disabled:opacity-60"
                  >
                    {createComment.isPending ? 'Salvataggio...' : 'Aggiungi commento'}
                  </button>
                  <button
                    onClick={() => {
                      setSelection(null);
                      setCommentText('');
                      setAuthorName('');
                      window.getSelection()?.removeAllRanges();
                    }}
                    className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 hover:bg-white/10"
                  >
                    Pulisci selezione
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-400">
                Seleziona un passaggio del manuale per ancorare un commento a quel testo.
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
            <div className="border-b border-white/10 px-5 py-4">
              <p className="text-xs uppercase tracking-[0.28em] text-fuchsia-200/70">Flusso Commenti</p>
              <h3 className="text-lg font-semibold text-white mt-1">Feedback sul manuale</h3>
            </div>
            <div className="border-b border-white/10 px-5 py-4 space-y-3 bg-slate-950/20">
              <input
                value={resolutionAuthor}
                onChange={(event) => setResolutionAuthor(event.target.value)}
                placeholder="Nome per risoluzioni e risposte (opzionale)"
                className="w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
              />
              {updateComment.error && (
                <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
                  Errore aggiornamento commento: {updateComment.error.message}
                </div>
              )}
            </div>
            <div className="max-h-[52vh] overflow-y-auto divide-y divide-white/10">
              {architectureComments.length === 0 ? (
                <div className="px-5 py-6 text-sm text-slate-400">Nessun commento ancora.</div>
              ) : (
                architectureComments.map((comment) => (
                  <div key={comment.id} className="px-5 py-4 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className={`rounded-full border px-3 py-1 text-xs ${statusBadgeClass(comment.status)}`}>
                        {comment.status}
                      </span>
                      {comment.resolved_at && (
                        <span className="text-xs text-slate-400">
                          aggiornato {new Date(comment.resolved_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                    <blockquote className="rounded-2xl border border-white/10 bg-slate-950/45 px-3 py-3 text-sm text-slate-200">
                      {comment.selected_text}
                    </blockquote>
                    <p className="text-sm text-slate-100">{comment.comment_text}</p>
                    {comment.resolution_note && (
                      <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-3 text-sm text-slate-200">
                        <p className="text-xs uppercase tracking-wide text-fuchsia-200/70 mb-2">Nota di chiusura</p>
                        <p>{comment.resolution_note}</p>
                        {(comment.resolved_by || comment.resolved_at) && (
                          <p className="mt-2 text-xs text-slate-400">
                            {comment.resolved_by || 'Sistema'}
                            {comment.resolved_at ? ` • ${new Date(comment.resolved_at).toLocaleString()}` : ''}
                          </p>
                        )}
                      </div>
                    )}
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                      <span>{comment.author_name || 'Anonimo'}</span>
                      <span>•</span>
                      <span>{new Date(comment.created_at).toLocaleString()}</span>
                      {comment.selection_start !== null && comment.selection_end !== null && (
                        <>
                          <span>•</span>
                          <span>
                            caratteri {comment.selection_start}-{comment.selection_end}
                          </span>
                        </>
                      )}
                    </div>
                    {comment.status === 'open' ? (
                      <div className="space-y-3">
                        <textarea
                          value={resolutionNotes[comment.id] ?? ''}
                          onChange={(event) =>
                            setResolutionNotes((current) => ({ ...current, [comment.id]: event.target.value }))
                          }
                          placeholder="Nota di risoluzione o motivazione (opzionale)"
                          className="w-full min-h-[6rem] rounded-2xl border border-white/10 bg-slate-900/70 px-3 py-3 text-sm text-slate-100 placeholder:text-slate-500"
                        />
                        <div className="flex flex-wrap items-center gap-3">
                          <button
                            onClick={() => submitResolution(comment.id, 'resolved')}
                            disabled={updateComment.isPending}
                            className="rounded-full border border-emerald-300/25 bg-emerald-400/20 px-4 py-2 text-sm text-emerald-50 hover:bg-emerald-400/25 disabled:opacity-60"
                          >
                            Segna come risolto
                          </button>
                          <button
                            onClick={() => submitResolution(comment.id, 'wontfix')}
                            disabled={updateComment.isPending}
                            className="rounded-full border border-amber-300/25 bg-amber-400/20 px-4 py-2 text-sm text-amber-50 hover:bg-amber-400/25 disabled:opacity-60"
                          >
                            Segna come non risolto
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-center gap-3">
                        <button
                          onClick={() => reopenComment(comment.id)}
                          disabled={updateComment.isPending}
                          className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 hover:bg-white/10 disabled:opacity-60"
                        >
                          Riapri commento
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ManualView;
