import { useEffect, useState } from 'react';
import { getRuntimeSettings, probeRuntimeSettings, saveRuntimeSettings } from '../api/client';
import type { RemoteBackendStatus, RuntimeMLSettings } from '../types';

const groups: Array<{
  title: string;
  description: string;
  endpoint: keyof RuntimeMLSettings;
  model: keyof RuntimeMLSettings;
}> = [
  { title: 'Knowledge e chat', description: 'Classificazione, specialisti e agente di consultazione.', endpoint: 'llm_endpoint', model: 'llm_model' },
  { title: 'Embedding', description: 'Indicizzazione e ricerca semantica.', endpoint: 'embedding_endpoint', model: 'embedding_model' },
  { title: 'OCR vision', description: 'Analisi visuale delle pagine.', endpoint: 'ocr_vision_endpoint', model: 'ocr_vision_model' },
  { title: 'OCR dots', description: 'Estrazione strutturata di testo e tabelle.', endpoint: 'ocr_dots_endpoint', model: 'ocr_dots_model' },
];

function ProbeResult({ result }: { result: RemoteBackendStatus }) {
  const tone = result.status === 'ok' ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100' : result.status === 'degraded' ? 'border-amber-400/30 bg-amber-400/10 text-amber-100' : 'border-rose-400/30 bg-rose-400/10 text-rose-100';
  return (
    <div className={`rounded-xl border p-3 text-sm ${tone}`}>
      <div className="flex items-center justify-between gap-3"><strong>{result.name}</strong><span>{result.latency_ms == null ? result.status : `${result.latency_ms} ms`}</span></div>
      <p className="mt-1 break-words text-xs opacity-80">{result.detail}</p>
    </div>
  );
}

export default function SettingsView() {
  const [values, setValues] = useState<RuntimeMLSettings | null>(null);
  const [defaults, setDefaults] = useState<RuntimeMLSettings | null>(null);
  const [overrides, setOverrides] = useState<string[]>([]);
  const [probes, setProbes] = useState<RemoteBackendStatus[]>([]);
  const [busy, setBusy] = useState<'load' | 'probe' | 'save' | null>('load');
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    getRuntimeSettings().then((response) => {
      setValues(response.values); setDefaults(response.environment_defaults); setOverrides(response.overridden_keys);
    }).catch((error) => setMessage(String(error))).finally(() => setBusy(null));
  }, []);

  const update = (key: keyof RuntimeMLSettings, value: string) => setValues((current) => current ? { ...current, [key]: value } : current);
  const runProbe = async () => {
    if (!values) return;
    setBusy('probe'); setMessage(null); setProbes([]);
    try { setProbes((await probeRuntimeSettings(values)).backends); } catch (error) { setMessage(String(error)); } finally { setBusy(null); }
  };
  const save = async () => {
    if (!values) return;
    setBusy('save'); setMessage(null);
    try {
      const response = await saveRuntimeSettings(values);
      setValues(response.values); setDefaults(response.environment_defaults); setOverrides(response.overridden_keys);
      setMessage('Impostazioni salvate. Saranno usate dai nuovi job.');
    } catch (error) { setMessage(String(error)); } finally { setBusy(null); }
  };

  if (!values || !defaults) return <div className="rounded-xl border border-white/10 bg-slate-900/70 p-6">{message || 'Caricamento impostazioni...'}</div>;
  return (
    <section className="mx-auto max-w-5xl space-y-5">
      <header><h2 className="text-2xl font-semibold text-white">Settings</h2><p className="mt-1 text-sm text-slate-400">Configurazione runtime dei backend OpenAI-compatible. Gli indirizzi sono risolti dai container: per un server sul Mac usa <code>http://host.docker.internal:8080/v1</code>.</p></header>
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map((group) => <div key={group.title} className="rounded-2xl border border-white/10 bg-slate-900/75 p-5">
          <h3 className="font-semibold text-white">{group.title}</h3><p className="mb-4 text-xs text-slate-400">{group.description}</p>
          <label className="block text-xs font-medium text-slate-300">Endpoint<input value={values[group.endpoint]} onChange={(event) => update(group.endpoint, event.target.value)} className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/50" /></label>
          <label className="mt-3 block text-xs font-medium text-slate-300">Modello<input value={values[group.model]} onChange={(event) => update(group.model, event.target.value)} className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/50" /></label>
          <p className="mt-2 text-[11px] text-slate-500">Default ambiente: {defaults[group.model]} · {overrides.includes(group.model) || overrides.includes(group.endpoint) ? 'override persistente' : 'nessun override'}</p>
        </div>)}
      </div>
      <div className="flex flex-wrap gap-3"><button disabled={busy !== null} onClick={runProbe} className="rounded-xl border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-100 disabled:opacity-40">{busy === 'probe' ? 'Verifica...' : 'Verifica backend'}</button><button disabled={busy !== null} onClick={save} className="rounded-xl bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-40">{busy === 'save' ? 'Salvataggio...' : 'Salva'}</button></div>
      {message && <p className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm text-slate-200">{message}</p>}
      {probes.length > 0 && <div className="grid gap-3 md:grid-cols-2">{probes.map((result) => <ProbeResult key={result.name} result={result} />)}</div>}
    </section>
  );
}
