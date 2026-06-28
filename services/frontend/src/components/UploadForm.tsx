import { useState } from 'react';
import { useUploadDocument } from '../hooks/useDocuments';

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function slugifyFilename(name: string) {
  return name
    .replace(/\.[^.]+$/, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
}

function UploadForm() {
  const [files, setFiles] = useState<File[]>([]);
  const [externalId, setExternalId] = useState('');
  const [autoSubmit, setAutoSubmit] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [uploadingIndex, setUploadingIndex] = useState<number | null>(null);

  const uploadMutation = useUploadDocument();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return;

    try {
      for (const [index, file] of files.entries()) {
        setUploadingIndex(index);
        const perFileExternalId = externalId
          ? files.length === 1
            ? externalId
            : `${externalId}-${String(index + 1).padStart(2, '0')}-${slugifyFilename(file.name)}`
          : undefined;
        await uploadMutation.mutateAsync({
          file,
          externalId: perFileExternalId,
          autoSubmit,
        });
      }
      setMessage({
        type: 'success',
        text: files.length === 1 ? 'Caricato con successo!' : `Caricati ${files.length} documenti con successo!`,
      });
      setFiles([]);
      setExternalId('');
    } catch (err) {
      setMessage({
        type: 'error',
        text: (err as Error).message,
      });
    } finally {
      setUploadingIndex(null);
    }
  };

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 shadow">
      <h2 className="mb-4 text-xl font-semibold text-slate-100">Caricamento Documento</h2>

      {message && (
        <div
          className={`mb-4 p-3 rounded ${
            message.type === 'success'
              ? 'border border-emerald-300/25 bg-emerald-400/10 text-emerald-100'
              : 'border border-rose-300/25 bg-rose-400/10 text-rose-100'
          }`}
        >
          {message.text}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-200">File PDF</label>
          <input
            type="file"
            accept="application/pdf"
            multiple
            onChange={(e) => {
              setFiles(Array.from(e.target.files ?? []));
              setMessage(null);
            }}
            className="block w-full rounded-md border border-slate-600 bg-slate-950 p-2 text-sm text-slate-100 file:mr-4 file:rounded-md file:border-0 file:bg-cyan-400/15 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-cyan-100 hover:file:bg-cyan-400/25"
            required
          />
          <p className="mt-1 text-xs text-slate-400">
            Puoi selezionare più PDF dal selettore del sistema.
          </p>
          {files.length > 0 && (
            <div className="mt-3 max-h-56 overflow-y-auto rounded-xl border border-white/10 bg-slate-950/45 p-2">
              <div className="mb-2 flex items-center justify-between gap-2 px-1 text-xs text-slate-400">
                <span>{files.length} file selezionati</span>
                <button
                  type="button"
                  onClick={() => setFiles([])}
                  disabled={uploadMutation.isPending}
                  className="text-slate-300 hover:text-white disabled:opacity-40"
                >
                  Svuota
                </button>
              </div>
              <div className="space-y-1.5">
                {files.map((selectedFile, index) => (
                  <div
                    key={`${selectedFile.name}-${selectedFile.size}-${index}`}
                    className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 flex-1 truncate text-slate-100">{selectedFile.name}</span>
                    <span className="shrink-0 text-xs text-slate-400">{formatBytes(selectedFile.size)}</span>
                    {uploadingIndex === index && (
                      <span className="shrink-0 rounded-full border border-cyan-300/25 bg-cyan-400/15 px-2 py-0.5 text-xs text-cyan-100">
                        upload
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-200">
            ID esterno (opzionale)
          </label>
          <input
            type="text"
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
            placeholder="es. contratto-001"
            className="block w-full rounded-md border border-slate-600 bg-slate-950 p-2 text-sm text-slate-100 placeholder:text-slate-500"
          />
          <p className="mt-1 text-xs text-slate-400">
            Con più file viene usato come prefisso per generare ID distinti.
          </p>
        </div>

        <div className="flex items-center">
          <input
            type="checkbox"
            id="autoSubmit"
            checked={autoSubmit}
            onChange={(e) => setAutoSubmit(e.target.checked)}
            className="mr-2"
          />
          <label htmlFor="autoSubmit" className="text-sm text-slate-200">
            Invio automatico del lavoro OCR dopo il caricamento
          </label>
        </div>

        <button
          type="submit"
          disabled={uploadMutation.isPending || files.length === 0}
          className="rounded-md bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {uploadMutation.isPending
            ? `Caricamento ${uploadingIndex !== null ? uploadingIndex + 1 : 1}/${files.length}...`
            : files.length > 1
              ? `Carica ${files.length} file`
              : 'Carica'}
        </button>
      </form>
    </div>
  );
}

export default UploadForm;
