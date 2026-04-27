import { useEffect, useState } from 'react';
import DocumentList from './components/DocumentList';
import DocumentDetail from './components/DocumentDetail';
import UploadForm from './components/UploadForm';
import JobStatus from './components/JobStatus';
import KnowledgeBase from './components/KnowledgeBase';

type View = 'documents' | 'knowledge' | 'upload';
type DocumentTab = 'info' | 'pdf' | 'ocr' | 'knowledge' | 'versions' | 'assets';

interface RouteState {
  view: View;
  selectedDoc: string | null;
  initialTab: DocumentTab;
}

function parseRoute(): RouteState {
  const { pathname, search } = window.location;
  const params = new URLSearchParams(search);
  const tab = (params.get('tab') as DocumentTab | null) ?? 'info';

  if (pathname === '/knowledge') {
    return { view: 'knowledge', selectedDoc: null, initialTab: 'knowledge' };
  }
  if (pathname === '/upload') {
    return { view: 'upload', selectedDoc: null, initialTab: 'info' };
  }
  if (pathname.startsWith('/documents/')) {
    const documentId = pathname.replace('/documents/', '').trim();
    return {
      view: 'documents',
      selectedDoc: documentId || null,
      initialTab: tab,
    };
  }
  return { view: 'documents', selectedDoc: null, initialTab: 'info' };
}

function App() {
  const [route, setRoute] = useState<RouteState>(() => parseRoute());

  useEffect(() => {
    const handlePopState = () => setRoute(parseRoute());
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (next: RouteState, replace = false) => {
    let url = '/';
    if (next.view === 'knowledge' && !next.selectedDoc) {
      url = '/knowledge';
    } else if (next.view === 'upload' && !next.selectedDoc) {
      url = '/upload';
    } else if (next.selectedDoc) {
      url = `/documents/${next.selectedDoc}`;
      if (next.initialTab !== 'info') {
        url += `?tab=${next.initialTab}`;
      }
    }

    window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
    setRoute(next);
  };

  const openView = (view: View) => {
    navigate({
      view,
      selectedDoc: null,
      initialTab: view === 'knowledge' ? 'knowledge' : 'info',
    });
  };

  const openDocument = (documentId: string, initialTab: DocumentTab = 'info') => {
    navigate({
      view: 'documents',
      selectedDoc: documentId,
      initialTab,
    });
  };

  const activeView = route.selectedDoc ? 'documents' : route.view;

  return (
    <div className="min-h-screen text-slate-100 bg-[radial-gradient(circle_at_top_left,_rgba(45,212,191,0.18),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(59,130,246,0.18),_transparent_30%),linear-gradient(180deg,_#07111f_0%,_#091827_48%,_#0b1220_100%)]">
      <div className="absolute inset-0 pointer-events-none opacity-40 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:32px_32px]" />

      <header className="sticky top-0 z-20 backdrop-blur-xl bg-slate-950/55 border-b border-white/10">
        <div className="max-w-7xl mx-auto px-5 py-4 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-cyan-300/80">Megadoc Knowledge Console</p>
            <h1 className="text-2xl lg:text-3xl font-semibold text-white">Document intelligence, now navigable</h1>
          </div>

          <nav className="flex flex-wrap items-center gap-2">
            {[
              { id: 'documents', label: 'Documents' },
              { id: 'knowledge', label: 'Knowledge' },
              { id: 'upload', label: 'Upload' },
            ].map((item) => (
              <button
                key={item.id}
                onClick={() => openView(item.id as View)}
                className={`px-4 py-2 rounded-full text-sm font-medium transition ${
                  activeView === item.id
                    ? 'bg-cyan-400/15 text-cyan-200 border border-cyan-300/30 shadow-[0_0_30px_rgba(34,211,238,0.18)]'
                    : 'bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10'
                }`}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="relative max-w-7xl mx-auto px-5 py-8">
        {!route.selectedDoc && (
          <section className="mb-8 rounded-[28px] border border-white/10 bg-white/5 backdrop-blur-md shadow-[0_24px_80px_rgba(0,0,0,0.35)] overflow-hidden">
            <div className="grid gap-6 lg:grid-cols-[1.4fr_0.9fr] p-6 lg:p-8">
              <div>
                <p className="text-sm text-cyan-200/80 mb-3">OCR, routing, consolidation and topic memory in one surface.</p>
                <h2 className="text-3xl lg:text-5xl leading-tight font-semibold text-white">
                  Navigate the corpus as a living knowledge graph, not a pile of PDFs.
                </h2>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-2xl border border-cyan-300/15 bg-slate-900/45 p-4">
                  <p className="text-cyan-200/70">Mode</p>
                  <p className="mt-2 text-lg font-semibold text-white">{activeView}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-slate-900/45 p-4">
                  <p className="text-cyan-200/70">Route</p>
                  <p className="mt-2 text-lg font-semibold text-white">{window.location.pathname}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-slate-900/45 p-4 col-span-2">
                  <p className="text-cyan-200/70">Use directly</p>
                  <p className="mt-2 text-slate-200">
                    `/knowledge` now opens the human interface. API calls live under `/api/*`.
                  </p>
                </div>
              </div>
            </div>
          </section>
        )}

        {route.selectedDoc ? (
          <DocumentDetail
            documentId={route.selectedDoc}
            initialTab={route.initialTab}
            onBack={() => openView(route.initialTab === 'knowledge' ? 'knowledge' : 'documents')}
          />
        ) : route.view === 'upload' ? (
          <UploadForm />
        ) : route.view === 'knowledge' ? (
          <KnowledgeBase onOpenDocument={(documentId) => openDocument(documentId, 'knowledge')} />
        ) : (
          <div className="grid gap-6 xl:grid-cols-[1.35fr_0.85fr]">
            <DocumentList onSelectDocument={(documentId) => openDocument(documentId)} />
            <JobStatus />
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
