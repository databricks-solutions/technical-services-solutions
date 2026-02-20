'use client';

import { useState, useEffect, lazy, Suspense } from 'react';
import { Network, FolderOpen, TrendingUp } from 'lucide-react';
import api from '@/lib/api';
import { ErrorBoundary } from '@/components';

// Lazy load heavy components for better performance
const LineageContainer = lazy(() => import('@/components/LineageContainer'));
const FilesManagementView = lazy(() => import('@/components/FilesManagementView'));
const InsightsView = lazy(() => import('@/components/InsightsView'));

type TabValue = 'insights' | 'lineage' | 'files';

export default function UnifiedDashboard() {
  const [activeTab, setActiveTab] = useState<TabValue>('insights');
  const [isHealthy, setIsHealthy] = useState(false);
  const [version, setVersion] = useState('');
  const [lineageFilterNodeId, setLineageFilterNodeId] = useState<string | null>(null);
  const [fileCount, setFileCount] = useState<number>(0);

  useEffect(() => {
    // Check API health and fetch files
    Promise.all([
      api.healthCheck()
        .then((health) => {
          setIsHealthy(health.status === 'healthy');
          setVersion(health.version);
        })
        .catch(() => setIsHealthy(false)),
      api.listFiles()
        .then((response) => {
          setFileCount(response.files?.length || 0);
        })
        .catch(() => setFileCount(0))
    ]);
  }, []);
  
  // Handler to switch to lineage tab with a file filter
  const handleViewFileLineage = (nodeId: string) => {
    setLineageFilterNodeId(nodeId);
    setActiveTab('lineage');
  };

  // Handler to refresh file count (called after upload/delete)
  const handleFilesChanged = () => {
    api.listFiles()
      .then((response) => {
        setFileCount(response.files?.length || 0);
      })
      .catch(() => setFileCount(0));
  };

  // Handler to navigate to insights after successful upload
  const handleUploadSuccess = () => {
    setActiveTab('insights');
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      <main className="container mx-auto px-6 py-8">
        {/* API Status */}
        <div className="flex justify-end mb-4">
          <div className={`px-4 py-2 rounded-full text-sm font-semibold ${
            isHealthy 
              ? 'bg-green-100 text-green-800' 
              : 'bg-red-100 text-red-800'
          }`}>
            API: {isHealthy ? '● Online' : '● Offline'} {version && `(v${version})`}
          </div>
        </div>

        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            Migration Accelerator Dashboard
          </h1>
          <p className="text-gray-600 text-lg">
            Plan and execute your migration with confidence - see impact, prioritize work, reduce risk
          </p>
        </div>

        {/* Tabs */}
        <div className="mb-6">
          <div className="border-b border-gray-200">
            <nav className="-mb-px flex space-x-8" aria-label="Tabs">
              <button
                onClick={() => setActiveTab('insights')}
                className={`
                  py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors
                  ${activeTab === 'insights'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }
                `}
              >
                <TrendingUp className="w-5 h-5" />
                <span>Insights</span>
              </button>
              <button
                onClick={() => setActiveTab('lineage')}
                className={`
                  py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors
                  ${activeTab === 'lineage'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }
                `}
              >
                <Network className="w-5 h-5" />
                <span>Lineage</span>
              </button>
              <button
                onClick={() => setActiveTab('files')}
                className={`
                  py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors
                  ${activeTab === 'files'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }
                `}
              >
                <FolderOpen className="w-5 h-5" />
                <span>Files & Metrics</span>
                {fileCount > 0 && (
                  <span className={`ml-1 px-2 py-0.5 text-xs rounded-full ${
                    activeTab === 'files'
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-gray-200 text-gray-700'
                  }`}>
                    {fileCount}
                  </span>
                )}
              </button>
            </nav>
          </div>
        </div>

        {/* Tab Content */}
        <ErrorBoundary>
          <Suspense fallback={
            <div className="space-y-6 animate-pulse">
              {/* Generic tab content skeleton */}
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex-1">
                    <div className="h-8 bg-gray-200 rounded w-80 mb-2" />
                    <div className="h-4 bg-gray-200 rounded w-96" />
                  </div>
                  <div className="h-10 w-36 bg-gray-200 rounded" />
                </div>
                <div className="space-y-4">
                  {[1, 2, 3, 4].map((i) => (
                    <div key={i} className="border border-gray-200 rounded-lg p-4">
                      <div className="h-5 bg-gray-200 rounded w-64 mb-3" />
                      <div className="space-y-2">
                        <div className="h-4 bg-gray-200 rounded w-full" />
                        <div className="h-4 bg-gray-200 rounded w-5/6" />
                        <div className="h-4 bg-gray-200 rounded w-4/6" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          }>
            <div className="animate-fade-in">
              {activeTab === 'insights' && <InsightsView onViewFileLineage={handleViewFileLineage} hasFiles={fileCount > 0} onNavigateToFiles={() => setActiveTab('files')} />}
              {activeTab === 'lineage' && <LineageContainer filterNodeId={lineageFilterNodeId} onClearFilter={() => setLineageFilterNodeId(null)} hasFiles={fileCount > 0} onNavigateToFiles={() => setActiveTab('files')} />}
              {activeTab === 'files' && <FilesManagementView onFilesChanged={handleFilesChanged} onUploadSuccess={handleUploadSuccess} />}
            </div>
          </Suspense>
        </ErrorBoundary>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-16">
        <div className="container mx-auto px-6 py-6 text-center text-gray-600">
          <p className="text-sm">
            © 2026 Migration Accelerator. Built with ❤️ by the Databricks Field Engineering Team.
          </p>
        </div>
      </footer>
    </div>
  );
}
