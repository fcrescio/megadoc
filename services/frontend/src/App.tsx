import { useState } from 'react';
import DocumentList from './components/DocumentList';
import DocumentDetail from './components/DocumentDetail';
import UploadForm from './components/UploadForm';
import JobStatus from './components/JobStatus';

function App() {
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">Megadoc</h1>
          <nav className="space-x-4">
            <button
              onClick={() => setSelectedDoc(null)}
              className={`px-3 py-2 rounded-md text-sm font-medium ${
                !selectedDoc ? 'bg-blue-50 text-blue-700' : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              Documents
            </button>
            <button
              onClick={() => setSelectedDoc(null)}
              className="px-3 py-2 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-100"
            >
              Jobs
            </button>
            <button
              onClick={() => setSelectedDoc(null)}
              className="px-3 py-2 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-100"
            >
              Upload
            </button>
          </nav>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        {selectedDoc ? (
          <DocumentDetail documentId={selectedDoc} onBack={() => setSelectedDoc(null)} />
        ) : (
          <>
            <DocumentList onSelectDocument={setSelectedDoc} />
            <JobStatus />
          </>
        )}
      </main>
    </div>
  );
}

export default App;
