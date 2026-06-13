import React, { Profiler, type ProfilerOnRenderCallback } from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './index.css';

declare global {
  interface Window {
    __MEGADOC_REACT_PROFILE__?: Array<{
      id: string;
      phase: string;
      actualDuration: number;
      baseDuration: number;
      startTime: number;
      commitTime: number;
    }>;
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 2,
    },
  },
});

function shouldProfileReact() {
  const params = new URLSearchParams(window.location.search);
  return params.get('react_profile') === '1' || window.localStorage.getItem('megadoc.reactProfile') === '1';
}

const handleRenderProfile: ProfilerOnRenderCallback = (
  id,
  phase,
  actualDuration,
  baseDuration,
  startTime,
  commitTime
) => {
  const bucket = window.__MEGADOC_REACT_PROFILE__ ?? [];
  bucket.push({
    id,
    phase,
    actualDuration: Math.round(actualDuration * 10) / 10,
    baseDuration: Math.round(baseDuration * 10) / 10,
    startTime: Math.round(startTime * 10) / 10,
    commitTime: Math.round(commitTime * 10) / 10,
  });
  window.__MEGADOC_REACT_PROFILE__ = bucket;
};

const app = (
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>
);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {shouldProfileReact() ? (
      <Profiler id="MegadocApp" onRender={handleRenderProfile}>
        {app}
      </Profiler>
    ) : (
      app
    )}
  </React.StrictMode>
);
