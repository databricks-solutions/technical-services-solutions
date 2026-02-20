'use client';

import { X, Database, FileText, ArrowUpCircle, ArrowDownCircle, Info } from 'lucide-react';
import { Card, Button } from '@/components';
import { truncateFilePath } from '@/lib/path-utils';
import { getNodeTypeDisplayName } from '@/types/nodeTypes';

interface NodeSource {
  file_id: string;
  filename: string;
  lineage_id: string;
}

interface DetailNode {
  id: string;
  name: string;
  type: string;
  properties?: {
    external_creation?: boolean;
    tags?: string[];
    [key: string]: any;
  };
  sources: NodeSource[];
  upstreamCount?: number;
  downstreamCount?: number;
}

interface NodeDetailPanelProps {
  nodes: DetailNode[];
  onRemoveNode: (nodeId: string) => void;
  onClearAll: () => void;
}

export default function NodeDetailPanel({
  nodes,
  onRemoveNode,
  onClearAll,
}: NodeDetailPanelProps) {
  if (nodes.length === 0) return null;

  return (
    <Card className="sticky top-4 mb-4">
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 flex items-center">
            <Database className="w-5 h-5 mr-2 text-blue-600" />
            Selected Nodes ({nodes.length})
          </h3>
          <Button
            onClick={onClearAll}
            variant="secondary"
            size="sm"
          >
            <X className="w-4 h-4 mr-1" />
            Clear All
          </Button>
        </div>

        <div className="space-y-3 max-h-96 overflow-y-auto">
          {nodes.map((node) => (
            <div
              key={node.id}
              className="p-3 bg-gray-50 rounded-lg border border-gray-200 hover:border-gray-300 transition-colors"
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex-1 min-w-0">
                  <h4 className="font-medium text-gray-900 text-sm break-words flex items-center gap-1" title={node.name}>
                    {truncateFilePath(node.name)}
                    {/* Show external creation tooltip for tables without CREATE statement */}
                    {(node.properties?.external_creation === true || 
                      node.properties?.tags?.includes('external_creation')) && (
                      <span 
                        className="inline-flex items-center text-orange-500 hover:text-orange-700 transition-colors cursor-help"
                        title="⚠️ No CREATE statement found - This table is referenced but never created in any loaded files. It may be pre-existing or externally managed."
                      >
                        <Info className="w-3.5 h-3.5" />
                      </span>
                    )}
                  </h4>
                  <p className="text-xs text-gray-500 font-medium mt-1">
                    {getNodeTypeDisplayName(node.type)}
                  </p>
                </div>
                <button
                  onClick={() => onRemoveNode(node.id)}
                  className="ml-2 text-gray-400 hover:text-red-600 transition-colors"
                  aria-label="Remove from selection"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Connection counts */}
              {(node.upstreamCount !== undefined || node.downstreamCount !== undefined) && (
                <div className="flex items-center space-x-4 mb-2">
                  {node.upstreamCount !== undefined && (
                    <div className="flex items-center text-xs text-gray-600">
                      <ArrowUpCircle className="w-3.5 h-3.5 mr-1 text-blue-500" />
                      <span>{node.upstreamCount} upstream</span>
                    </div>
                  )}
                  {node.downstreamCount !== undefined && (
                    <div className="flex items-center text-xs text-gray-600">
                      <ArrowDownCircle className="w-3.5 h-3.5 mr-1 text-green-500" />
                      <span>{node.downstreamCount} downstream</span>
                    </div>
                  )}
                </div>
              )}

              {/* Source files */}
              {node.sources && node.sources.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-200">
                  <p className="text-xs font-medium text-gray-700 mb-1.5 flex items-center">
                    <FileText className="w-3 h-3 mr-1" />
                    Source Files ({node.sources.length})
                  </p>
                  <div className="space-y-1">
                    {node.sources.slice(0, 3).map((source, idx) => (
                      <p
                        key={idx}
                        className="text-xs text-gray-600 break-words"
                        title={source.filename}
                      >
                        {truncateFilePath(source.filename)}
                      </p>
                    ))}
                    {node.sources.length > 3 && (
                      <p className="text-xs text-gray-500 italic">
                        +{node.sources.length - 3} more
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

