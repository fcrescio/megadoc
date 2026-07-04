import { Suspense, lazy, useEffect, useState } from 'react';
import DocumentList from './components/DocumentList';
import JobStatus from './components/JobStatus';
import SystemStatusButton from './components/SystemStatusButton';

const DocumentDetail = lazy(() => import('./components/DocumentDetail'));
const UploadForm = lazy(() => import('./components/UploadForm'));
const KnowledgeBase = lazy(() => import('./components/KnowledgeBase'));
const ManualView = lazy(() => import('./components/ManualView'));

type View = 'documents' | 'knowledge' | 'upload' | 'manual';
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
  if (pathname === '/manual') {
    return { view: 'manual', selectedDoc: null, initialTab: 'info' };
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

function RouteFallback() {
  return (
    <div className="rounded-3xl border border-sky-300/20 bg-indigo-950/50 p-6 text-sm text-sky-100">
      Caricamento...
    </div>
  );
}

function App() {
  const [route, setRoute] = useState<RouteState>(() => parseRoute());
  const [isMainNavCollapsed, setIsMainNavCollapsed] = useState(() => {
    return window.localStorage.getItem('megadoc.mainNavCollapsed') === 'true';
  });

  useEffect(() => {
    const handlePopState = () => setRoute(parseRoute());
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (next: RouteState, replace = false) => {
    let url = '/';
    if (next.view === 'knowledge' && !next.selectedDoc) {
      url = '/knowledge';
    } else if (next.view === 'manual' && !next.selectedDoc) {
      url = '/manual';
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
  const mainNavWidthClass = isMainNavCollapsed ? 'lg:w-20' : 'lg:w-60';
  const mainContentOffsetClass = isMainNavCollapsed ? 'lg:ml-20' : 'lg:ml-60';

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(251,191,36,0.20),transparent_28rem),radial-gradient(circle_at_top_right,rgba(34,211,238,0.22),transparent_34rem),radial-gradient(circle_at_bottom_right,rgba(168,85,247,0.22),transparent_34rem),linear-gradient(135deg,#050816_0%,#111342_42%,#172554_100%)] text-slate-100">
      <div className="absolute inset-0 pointer-events-none opacity-30 bg-[linear-gradient(rgba(251,191,36,0.07)_1px,transparent_1px),linear-gradient(90deg,rgba(34,211,238,0.08)_1px,transparent_1px)] bg-[size:30px_30px]" />

      <header className={`sticky top-0 z-20 border-b border-amber-300/20 bg-indigo-950/95 shadow-2xl shadow-indigo-950/40 backdrop-blur lg:fixed lg:inset-y-0 lg:left-0 ${mainNavWidthClass} lg:border-b-0 lg:border-r lg:transition-[width] lg:duration-200`}>
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-5 py-3 lg:h-full lg:px-4 lg:py-5">
          <div className={`flex items-start justify-between gap-2 ${isMainNavCollapsed ? 'lg:items-center lg:justify-center' : ''}`}>
            <div className={isMainNavCollapsed ? 'lg:hidden' : ''}>
              <p className="text-xs uppercase tracking-[0.35em] text-amber-200">Megadoc</p>
              <h1 className="text-lg font-semibold text-white">Console documentale</h1>
            </div>
            <button
              type="button"
              onClick={() => {
                const next = !isMainNavCollapsed;
                setIsMainNavCollapsed(next);
                window.localStorage.setItem('megadoc.mainNavCollapsed', String(next));
              }}
              title={isMainNavCollapsed ? 'Espandi menu' : 'Collassa menu'}
              className="hidden rounded-xl border border-amber-300/30 bg-amber-300/15 px-2.5 py-2 text-sm text-amber-100 transition hover:bg-amber-300/25 lg:block"
            >
              {isMainNavCollapsed ? '»' : '«'}
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-3 lg:min-h-0 lg:flex-1 lg:flex-col lg:items-stretch lg:justify-start">
            <nav className="flex flex-wrap items-center gap-2 lg:flex-col lg:items-stretch">
              {[
                { id: 'documents', label: 'Documenti', short: 'D' },
                { id: 'knowledge', label: 'Conoscenza', short: 'K' },
                { id: 'manual', label: 'Manuale', short: 'M' },
                { id: 'upload', label: 'Caricamento', short: 'U' },
              ].map((item) => (
                <button
                  key={item.id}
                  onClick={() => openView(item.id as View)}
                  title={item.label}
                  className={`rounded-full px-4 py-2 text-sm font-medium transition lg:w-full lg:rounded-xl ${
                    isMainNavCollapsed ? 'lg:px-2 lg:text-center' : 'lg:text-left'
                  } ${
                    activeView === item.id
                      ? 'border border-amber-300/55 bg-gradient-to-r from-amber-400/25 via-cyan-400/20 to-fuchsia-400/20 text-white shadow-lg shadow-amber-950/30'
                      : 'border border-sky-200/15 bg-indigo-900/45 text-sky-100 hover:border-amber-300/35 hover:bg-amber-300/15 hover:text-white'
                  }`}
                >
                  <span className={isMainNavCollapsed ? 'hidden lg:inline' : 'hidden'}>{item.short}</span>
                  <span className={isMainNavCollapsed ? 'lg:hidden' : ''}>{item.label}</span>
                </button>
              ))}
            </nav>
            <div className={isMainNavCollapsed ? 'lg:hidden' : ''}>
              <SystemStatusButton />
            </div>
          </div>
        </div>
      </header>

      <main className={`relative mx-auto max-w-7xl px-5 py-4 ${mainContentOffsetClass} lg:max-w-none lg:px-4 lg:transition-[margin] lg:duration-200`}>
        {!route.selectedDoc && route.view !== 'knowledge' && (
          <section className="mb-8 overflow-hidden rounded-xl border border-amber-300/25 bg-indigo-950/75 shadow-2xl shadow-indigo-950/40">
            <div className="grid gap-6 bg-gradient-to-br from-indigo-900/65 via-sky-950/45 to-fuchsia-950/45 p-6 lg:grid-cols-[1.4fr_0.9fr] lg:p-8">
              <div>
                <p className="mb-3 text-sm text-amber-100">OCR, classificazione e consultazione.</p>
                <h2 className="text-3xl lg:text-4xl leading-tight font-semibold text-white">Archivio dei documenti</h2>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-2xl border border-cyan-300/20 bg-cyan-400/10 p-4">
                  <p className="text-cyan-200/70">Mode</p>
                  <p className="mt-2 text-lg font-semibold text-white">{activeView}</p>
                </div>
                <div className="rounded-2xl border border-indigo-300/20 bg-indigo-400/10 p-4">
                  <p className="text-indigo-200/80">Route</p>
                  <p className="mt-2 text-lg font-semibold text-white">{window.location.pathname}</p>
                </div>
                <div className="rounded-2xl border border-emerald-300/20 bg-emerald-400/10 p-4 col-span-2">
                  <p className="text-emerald-200/80">Usa direttamente</p>
                  <p className="mt-2 text-slate-200">
                    `/knowledge` now opens the human interface. API calls live under `/api/*`.
                  </p>
                </div>
              </div>
            </div>
          </section>
        )}

        <Suspense fallback={<RouteFallback />}>
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
          ) : route.view === 'manual' ? (
            <ManualView />
          ) : (
            <div className="grid gap-6 xl:grid-cols-[1.35fr_0.85fr]">
              <DocumentList onSelectDocument={(documentId) => openDocument(documentId)} />
              <JobStatus />
            </div>
          )}
        </Suspense>
      </main>

      <footer className="fixed bottom-2 right-3 z-50 text-[10px] text-white/20 select-none">
        {__GIT_HASH__}
      </footer>
    </div>
  );
}

export default App;
