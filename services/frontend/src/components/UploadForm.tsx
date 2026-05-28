import { useState } from 'react';
import { useUploadDocument } from '../hooks/useDocuments';

function UploadForm() {
  const [file, setFile] = useState<File | null>(null);
  const [externalId, setExternalId] = useState('');
  const [autoSubmit, setAutoSubmit] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const uploadMutation = useUploadDocument();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    try {
      await uploadMutation.mutateAsync({
        file,
        externalId: externalId || undefined,
        autoSubmit,
      });
      setMessage({
        type: 'success',
        text: 'Caricato con successo!',
      });
      setFile(null);
      setExternalId('');
    } catch (err) {
      setMessage({
        type: 'error',
        text: (err as Error).message,
      });
    }
  };

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-xl font-semibold mb-4">Caricamento Documento</h2>

      {message && (
        <div
          className={`mb-4 p-3 rounded ${
            message.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
          }`}
        >
          {message.text}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">File PDF</label>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm border-gray-300 rounded-md border p-2"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            ID esterno (opzionale)
          </label>
          <input
            type="text"
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
            placeholder="es. contratto-001"
            className="block w-full text-sm border-gray-300 rounded-md border p-2"
          />
          <p className="text-xs text-gray-500 mt-1">
            Usa external_id per versionare lo stesso documento logico
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
          <label htmlFor="autoSubmit" className="text-sm text-gray-700">
            Invio automatico del lavoro OCR dopo il caricamento
          </label>
        </div>

        <button
          type="submit"
          disabled={uploadMutation.isPending || !file}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {uploadMutation.isPending ? 'Caricamento...' : 'Carica'}
        </button>
      </form>
    </div>
  );
}

export default UploadForm;
