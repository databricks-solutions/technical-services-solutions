'use client';

import { useState } from 'react';
import { Database, TrendingUp, ChevronDown, ChevronRight, FileText } from 'lucide-react';
import { Card } from '@/components';
import type { LineageInsightsResponse } from '@/lib/api';
import { truncateFilePath } from '@/lib/path-utils';
import { isTableNode, getNodeTypeDisplayName } from '@/types/nodeTypes';

interface Node {
  id: string;
  name: string;
  type: string;
  sources: Array<{
    file_id: string;
    filename: string;
    lineage_id: string;
  }>;
}

interface Link {
  source: string;
  target: string;
  relationship: string;
}

interface GraphData {
  nodes: Node[];
  links: Link[];
}

interface InsightsPanelProps {
  insights: LineageInsightsResponse | null;
  loading?: boolean;
  onFilterByNodes?: (nodeIds: string[], meta?: { type: string; label: string }) => void;
  onFilterByNodeId?: (nodeId: string, meta?: { type: string; label: string }) => void;
  visibleNodeIds?: Set<string>;
  graphData?: GraphData | null;
  activeInsightFilter?: { type: string; label: string } | null;
}

export default function InsightsPanel({ 
  insights, 
  loading, 
  onFilterByNodes,
  onFilterByNodeId,
  visibleNodeIds,
  graphData,
  activeInsightFilter
}: InsightsPanelProps) {
  if (loading) {
    return (
      <Card>
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      </Card>
    );
  }

  if (!insights) {
    return (
      <Card>
        <div className="text-center py-12 text-gray-500">
          <Database className="w-12 h-12 mx-auto mb-4 text-gray-400" />
          <p>No data available yet</p>
          <p className="text-sm mt-2">Upload files to see insights</p>
        </div>
      </Card>
    );
  }

  // Calculate dynamic visible counts
  const visibleFilesCount = visibleNodeIds && graphData 
    ? graphData.nodes.filter(n => n.type === 'FILE' && (visibleNodeIds.size === 0 || visibleNodeIds.has(n.id))).length
    : insights.total_files || 0;

  const visibleTablesCount = visibleNodeIds && graphData
    ? graphData.nodes.filter(n => isTableNode(n.type) && (visibleNodeIds.size === 0 || visibleNodeIds.has(n.id))).length
    : insights.total_tables || 0;

  return (
    <div className="space-y-6">
      {/* Files and Tables Statistics */}
      <div className="grid grid-cols-2 gap-4">
        {/* Total Files - NOT clickable, shows visible count */}
        <StatCard
          icon={<Database className="w-5 h-5" />}
          label={visibleNodeIds && visibleNodeIds.size > 0 ? "Files (Visible)" : "Total Files"}
          value={visibleFilesCount}
          color="blue"
        />
        {/* Total Tables/Views - NOT clickable, shows visible count */}
        <StatCard
          icon={<Database className="w-5 h-5" />}
          label={visibleNodeIds && visibleNodeIds.size > 0 ? "Tables (Visible)" : "Total Tables/Views"}
          value={visibleTablesCount}
          color="green"
        />
      </div>

      {/* Clickable Insights */}
      <div className="grid grid-cols-2 gap-4">
        {/* Tables Only Read - CLICKABLE */}
        <div 
          className={`bg-white rounded-xl shadow-lg p-4 cursor-pointer hover:shadow-xl transition-all border-2 ${
            activeInsightFilter?.type === 'tables_only_read'
              ? 'border-blue-500 bg-blue-50'
              : 'border-blue-200 hover:border-blue-400'
          }`}
          onClick={() => {
            if (onFilterByNodes && insights?.tables_only_read) {
              const nodeIds = insights.tables_only_read.map(t => t.node_id);
              onFilterByNodes(nodeIds, { 
                type: 'tables_only_read', 
                label: `${nodeIds.length} Tables Only Read` 
              });
            }
          }}
        >
          <div className="inline-flex p-2 rounded-lg mb-2 bg-blue-50 text-blue-600">
            <Database className="w-5 h-5" />
          </div>
          <p className="text-2xl font-bold text-gray-900">{insights.tables_only_read?.length || 0}</p>
          <p className="text-sm text-gray-600">Tables Only Read</p>
          {activeInsightFilter?.type === 'tables_only_read' ? (
            <p className="text-xs text-blue-700 mt-1 font-bold">✓ Active Filter</p>
          ) : onFilterByNodes && (
            <p className="text-xs text-blue-600 mt-1 font-medium">Click to filter graph →</p>
          )}
        </div>

        {/* Tables Never Read - CLICKABLE */}
        <div 
          className={`bg-white rounded-xl shadow-lg p-4 cursor-pointer hover:shadow-xl transition-all border-2 ${
            activeInsightFilter?.type === 'tables_never_read'
              ? 'border-green-500 bg-green-50'
              : 'border-green-200 hover:border-green-400'
          }`}
          onClick={() => {
            if (onFilterByNodes && insights?.tables_never_read) {
              const nodeIds = insights.tables_never_read.map(t => t.node_id);
              onFilterByNodes(nodeIds, { 
                type: 'tables_never_read', 
                label: `${nodeIds.length} Tables Never Read (confirm if needed)` 
              });
            }
          }}
        >
          <div className="inline-flex p-2 rounded-lg mb-2 bg-green-50 text-green-600">
            <TrendingUp className="w-5 h-5" />
          </div>
          <p className="text-2xl font-bold text-gray-900">{insights.tables_never_read?.length || 0}</p>
          <p className="text-sm text-gray-600">Tables Never Read</p>
          {activeInsightFilter?.type === 'tables_never_read' ? (
            <p className="text-xs text-green-700 mt-1 font-bold">✓ Active Filter</p>
          ) : onFilterByNodes && (
            <p className="text-xs text-green-600 mt-1 font-medium">Click to filter graph →</p>
          )}
        </div>
      </div>

      {/* Most Connected Nodes with File References */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-gray-900 flex items-center">
            <TrendingUp className="w-5 h-5 mr-2 text-blue-600" />
            Most Connected Tables/Views
          </h3>
        </div>
        
        {insights.most_connected.length === 0 ? (
          <p className="text-gray-500 text-center py-6">No connections found</p>
        ) : (
          <div className="space-y-2">
            {insights.most_connected.map((node, index) => (
              <MostConnectedNode
                key={node.node_id}
                node={node}
                index={index}
                onFilterByNodeId={onFilterByNodeId}
                activeInsightFilter={activeInsightFilter}
              />
            ))}
          </div>
        )}
      </Card>

    </div>
  );
}

// Component for Most Connected Node with expandable file references
interface MostConnectedNodeProps {
  node: {
    node_id: string;
    name: string;
    type: string;
    connection_count: number;
    file_references?: {
      creator_files: Array<{ file_id: string; filename: string }>;
      reads_from_files: Array<{ file_id: string; filename: string }>;
      writes_to_files: Array<{ file_id: string; filename: string }>;
    };
  };
  index: number;
  onFilterByNodeId?: (nodeId: string, meta?: { type: string; label: string }) => void;
  activeInsightFilter?: { type: string; label: string } | null;
}

function MostConnectedNode({ node, index, onFilterByNodeId, activeInsightFilter }: MostConnectedNodeProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  
  const hasFileReferences = node.file_references && (
    node.file_references.creator_files.length > 0 ||
    node.file_references.reads_from_files.length > 0 ||
    node.file_references.writes_to_files.length > 0
  );

  const isActive = activeInsightFilter?.type === 'most_connected' && 
                   activeInsightFilter?.label === node.name;

  return (
    <div className={`rounded-lg overflow-hidden ${isActive ? 'bg-blue-50 ring-2 ring-blue-500' : 'bg-gray-50'}`}>
      <div
        className="flex items-center justify-between p-3 hover:bg-gray-100 transition-colors cursor-pointer"
        onClick={() => {
          if (onFilterByNodeId) {
            onFilterByNodeId(node.node_id, { 
              type: 'most_connected', 
              label: node.name 
            });
          }
        }}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
            <span className="text-sm font-bold text-blue-700">
              #{index + 1}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-900 break-words" title={node.name}>
              {node.name}
            </p>
            {onFilterByNodeId && (
              <p className="text-xs text-blue-600 mt-0.5">Click to show in graph →</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold bg-blue-100 text-blue-800">
            {node.connection_count}
          </span>
          {hasFileReferences && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsExpanded(!isExpanded);
              }}
              className="p-1 hover:bg-gray-200 rounded transition-colors"
            >
              {isExpanded ? (
                <ChevronDown className="w-4 h-4 text-gray-600" />
              ) : (
                <ChevronRight className="w-4 h-4 text-gray-600" />
              )}
            </button>
          )}
        </div>
      </div>

      {/* Expandable File References */}
      {isExpanded && hasFileReferences && node.file_references && (
        <div className="px-3 pb-3 pt-0 space-y-3 bg-white border-t border-gray-200">
          {node.file_references.creator_files.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-purple-700 mb-1 flex items-center">
                <FileText className="w-3 h-3 mr-1" />
                Created By ({node.file_references.creator_files.length})
              </p>
              <div className="space-y-1">
                {node.file_references.creator_files.map((file) => (
                  <p key={file.file_id} className="text-xs text-gray-600 pl-4" title={file.filename}>
                    • {truncateFilePath(file.filename)}
                  </p>
                ))}
              </div>
            </div>
          )}

          {node.file_references.reads_from_files.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-blue-700 mb-1 flex items-center">
                <FileText className="w-3 h-3 mr-1" />
                Read By ({node.file_references.reads_from_files.length})
              </p>
              <div className="space-y-1">
                {node.file_references.reads_from_files.map((file) => (
                  <p key={file.file_id} className="text-xs text-gray-600 pl-4" title={file.filename}>
                    • {truncateFilePath(file.filename)}
                  </p>
                ))}
              </div>
            </div>
          )}

          {node.file_references.writes_to_files.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-green-700 mb-1 flex items-center">
                <FileText className="w-3 h-3 mr-1" />
                Written To By ({node.file_references.writes_to_files.length})
              </p>
              <div className="space-y-1">
                {node.file_references.writes_to_files.map((file) => (
                  <p key={file.file_id} className="text-xs text-gray-600 pl-4" title={file.filename}>
                    • {truncateFilePath(file.filename)}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: 'blue' | 'green' | 'purple' | 'orange';
}

function StatCard({ icon, label, value, color }: StatCardProps) {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
    orange: 'bg-orange-50 text-orange-600',
  };

  return (
    <Card className="p-4">
      <div className={`inline-flex p-2 rounded-lg mb-2 ${colorClasses[color]}`}>
        {icon}
      </div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-sm text-gray-600">{label}</p>
    </Card>
  );
}
