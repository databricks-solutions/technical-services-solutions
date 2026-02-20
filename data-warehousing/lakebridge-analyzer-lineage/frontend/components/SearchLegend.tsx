'use client';

import { Info } from 'lucide-react';
import { Card } from '@/components';

interface SearchLegendProps {
  visible: boolean;
  matchedNodeName?: string;
  upstreamCount: number;
  downstreamCount: number;
}

export default function SearchLegend({
  visible,
  matchedNodeName,
  upstreamCount,
  downstreamCount,
}: SearchLegendProps) {
  if (!visible) return null;

  return (
    <Card className="p-4">
      <div className="flex items-start space-x-3">
        <Info className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="font-semibold text-gray-900 mb-2">Search Results</h4>
          
          {matchedNodeName && (
            <p className="text-sm text-gray-700 mb-3">
              Showing connections for: <span className="font-semibold">{matchedNodeName}</span>
            </p>
          )}

          <div className="space-y-2">
            <div className="flex items-center space-x-2">
              <div className="w-4 h-4 rounded-full bg-yellow-400 border-2 border-yellow-600"></div>
              <span className="text-sm text-gray-700">
                <strong>Matched Node</strong> - Your search result
              </span>
            </div>

            <div className="flex items-center space-x-2">
              <div className="w-4 h-4 rounded-full bg-blue-500"></div>
              <span className="text-sm text-gray-700">
                <strong>Upstream ({upstreamCount})</strong> - Dependencies
              </span>
            </div>

            <div className="flex items-center space-x-2">
              <div className="w-4 h-4 rounded-full bg-green-500"></div>
              <span className="text-sm text-gray-700">
                <strong>Downstream ({downstreamCount})</strong> - Dependents
              </span>
            </div>

            <div className="flex items-center space-x-2">
              <div className="w-8 h-0.5 bg-orange-500"></div>
              <span className="text-sm text-gray-700">
                <strong>Highlighted Edges</strong> - Active connections
              </span>
            </div>
          </div>

          {/* Edge Relationship Types */}
          <div className="mt-4 pt-3 border-t border-gray-200">
            <p className="text-xs font-semibold text-gray-700 mb-2">Edge Relationship Types</p>
            <div className="space-y-1.5">
              <div className="flex items-center space-x-2">
                <div className="w-6 h-0.5 bg-blue-500"></div>
                <span className="text-xs text-gray-600">READS_FROM</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-6 h-0.5 bg-green-500"></div>
                <span className="text-xs text-gray-600">WRITES_TO (INSERT/UPDATE)</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-6 h-0.5 bg-red-500"></div>
                <span className="text-xs text-gray-600">DELETES_FROM (DELETE/TRUNCATE)</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-6 h-0.5 bg-purple-600"></div>
                <span className="text-xs text-gray-600">DROPS</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-6 h-0.5 bg-purple-500"></div>
                <span className="text-xs text-gray-600">CREATES</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-6 h-0.5 bg-gray-500"></div>
                <span className="text-xs text-gray-600">DEPENDS_ON</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}

