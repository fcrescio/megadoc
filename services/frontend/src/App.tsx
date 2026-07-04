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
type MainNavIcon = 'documents' | 'knowledge' | 'manual' | 'upload';

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
    <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-sm text-slate-300">
      Caricamento...
    </div>
  );
}

function NavIcon({ icon }: { icon: MainNavIcon }) {
  const common = {
    className: 'mx-auto h-4 w-4',
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.9,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  if (icon === 'documents') {
    return (
      <svg {...common}>
        <path d="M7 3.75h7l3 3v13.5H7z" />
        <path d="M14 3.75v3h3" />
        <path d="M9.5 11h5" />
        <path d="M9.5 15h5" />
      </svg>
    );
  }
  if (icon === 'knowledge') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="3" />
        <circle cx="5" cy="7" r="2" />
        <circle cx="19" cy="7" r="2" />
        <circle cx="7" cy="19" r="2" />
        <circle cx="17" cy="19" r="2" />
        <path d="M7 8.2 10 11" />
        <path d="m17 8.2-3 2.8" />
        <path d="m8.4 17.4 2.2-3" />
        <path d="m15.6 17.4-2.2-3" />
      </svg>
    );
  }
  if (icon === 'manual') {
    return (
      <svg {...common}>
        <path d="M5 4.5h8a3 3 0 0 1 3 3v12H8a3 3 0 0 0-3 3z" />
        <path d="M16 7.5h3v12h-3" />
        <path d="M8 8h4" />
        <path d="M8 12h5" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M5 16v3.25A1.75 1.75 0 0 0 6.75 21h10.5A1.75 1.75 0 0 0 19 19.25V16" />
    </svg>
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
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.18),transparent_34rem),radial-gradient(circle_at_bottom_right,rgba(129,140,248,0.16),transparent_32rem),linear-gradient(135deg,#020617_0%,#0f172a_48%,#111827_100%)] text-slate-100">
      <div className="absolute inset-0 pointer-events-none opacity-25 bg-[linear-gradient(rgba(125,211,252,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(125,211,252,0.08)_1px,transparent_1px)] bg-[size:32px_32px]" />

      <header className={`sticky top-0 z-20 border-b border-cyan-300/15 bg-slate-950/95 shadow-2xl shadow-cyan-950/20 backdrop-blur lg:fixed lg:inset-y-0 lg:left-0 ${mainNavWidthClass} lg:border-b-0 lg:border-r lg:transition-[width] lg:duration-200`}>
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-5 py-3 lg:h-full lg:px-4 lg:py-5">
          <div className={`flex items-start justify-between gap-2 ${isMainNavCollapsed ? 'lg:items-center lg:justify-center' : ''}`}>
            <div className={isMainNavCollapsed ? 'lg:hidden' : ''}>
              <p className="text-xs uppercase tracking-[0.35em] text-cyan-300/90">Megadoc</p>
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
              className="hidden rounded-xl border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-2 text-sm text-cyan-100 transition hover:bg-cyan-300/20 lg:block"
            >
              {isMainNavCollapsed ? '»' : '«'}
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-3 lg:min-h-0 lg:flex-1 lg:flex-col lg:items-stretch lg:justify-start">
            <nav className="flex flex-wrap items-center gap-2 lg:flex-col lg:items-stretch">
              {[
                { id: 'documents', label: 'Documenti', icon: 'documents' },
                { id: 'knowledge', label: 'Conoscenza', icon: 'knowledge' },
                { id: 'manual', label: 'Manuale', icon: 'manual' },
                { id: 'upload', label: 'Caricamento', icon: 'upload' },
              ].map((item) => (
                <button
                  key={item.id}
                  onClick={() => openView(item.id as View)}
                  title={item.label}
                  className={`rounded-full px-4 py-2 text-sm font-medium transition lg:w-full lg:rounded-xl ${
                    isMainNavCollapsed ? 'lg:px-2 lg:text-center' : 'lg:text-left'
                  } ${
                    activeView === item.id
                      ? 'border border-cyan-300/50 bg-gradient-to-r from-cyan-400/20 to-indigo-400/20 text-cyan-100 shadow-lg shadow-cyan-950/25'
                      : 'border border-white/10 bg-white/5 text-slate-300 hover:border-cyan-300/25 hover:bg-cyan-300/10 hover:text-white'
                  }`}
                >
                  <span className={isMainNavCollapsed ? 'hidden lg:inline' : 'hidden'}>
                    <NavIcon icon={item.icon as MainNavIcon} />
                  </span>
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
          <section className="mb-8 overflow-hidden rounded-xl border border-cyan-300/15 bg-slate-900/80 shadow-2xl shadow-cyan-950/20">
            <div className="grid gap-6 lg:grid-cols-[1.4fr_0.9fr] p-6 lg:p-8">
              <div>
                <p className="text-sm text-cyan-200/90 mb-3">OCR, classificazione e consultazione.</p>
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
