'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';

interface MetricsDashboardProps {
  analyzerId: string;
  metrics?: Record<string, any>;
}

export default function MetricsDashboard({ 
  analyzerId, 
  metrics: initialMetrics 
}: MetricsDashboardProps) {
  const [metrics, setMetrics] = useState(initialMetrics || {});
  const [loading, setLoading] = useState(!initialMetrics);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!initialMetrics) {
      loadMetrics();
    }
  }, [analyzerId, initialMetrics]);

  const loadMetrics = async () => {
    try {
      setLoading(true);
      const data = await api.getMetrics(analyzerId);
      setMetrics(data.metrics || {});
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load metrics');
      console.error('Failed to load metrics:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3 animate-pulse">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
          <div 
            key={i} 
            className="flex justify-between items-center py-3 border-b border-gray-100"
          >
            <div className="h-4 bg-gray-200 rounded w-32" />
            <div className="h-5 bg-gray-200 rounded w-20" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-red-600">{error}</p>
        <button 
          onClick={loadMetrics}
          className="mt-4 text-blue-600 hover:text-blue-700 font-semibold"
        >
          Try Again
        </button>
      </div>
    );
  }

  const metricEntries = Object.entries(metrics);

  if (metricEntries.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        <p>No metrics available</p>
      </div>
    );
  }

  // Format metric values
  const formatValue = (value: any): string => {
    if (typeof value === 'number') {
      return value.toLocaleString();
    }
    if (typeof value === 'boolean') {
      return value ? 'Yes' : 'No';
    }
    if (value === null || value === undefined) {
      return 'N/A';
    }
    return String(value);
  };

  // Format metric keys (convert snake_case to Title Case)
  const formatKey = (key: string): string => {
    return key
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  return (
    <div className="space-y-3">
      {metricEntries.map(([key, value]) => (
        <div 
          key={key} 
          className="flex justify-between items-center py-3 border-b border-gray-100 last:border-0"
        >
          <span className="text-gray-600 text-sm">{formatKey(key)}</span>
          <span className="font-semibold text-gray-900">{formatValue(value)}</span>
        </div>
      ))}
    </div>
  );
}



