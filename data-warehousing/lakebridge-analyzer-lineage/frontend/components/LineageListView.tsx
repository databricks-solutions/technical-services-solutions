'use client';

import { useState, useMemo, useEffect } from 'react';
import { GitBranch, ChevronDown, ChevronRight, ArrowUpDown, Download, Copy, Info, X } from 'lucide-react';
import { Card } from '@/components';
import { truncateFilePath } from '@/lib/path-utils';
import { NodeTypes, isTableNode, getNodeTypeDisplayName } from '@/types/nodeTypes';
import { getContextualRelationshipLabel, getRelationshipColor, formatOperationName } from '@/types/relationshipLabels';
import { computeConnections, enrichNodes, getConnections as getConnectionsUtil } from '@/lib/lineage-utils';

interface Node {
  id: string;
  name: string;
  type: string;
  properties?: {
    external_creation?: boolean;
    tags?: string[];
    [key: string]: any;
  };
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

interface LineageListViewProps {
  graphData: GraphData;
  activeInsightType?: string | null;
  filterType?: string;
  onFilterTypeChange?: (type: string) => void;
  selectedOperations?: Set<string>;
  sortField?: SortField;
  sortDirection?: SortDirection;
  onSortChange?: (field: SortField, direction: SortDirection) => void;
  loading?: boolean;
  selectedNodeIds?: Set<string>;
  onClearSelection?: () => void;
}

export type SortField = 'name' | 'type' | 'upstream' | 'downstream' | 'impact';
export type SortDirection = 'asc' | 'desc';

// Skeleton loader component for loading state
function ListViewSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="space-y-0">
      {Array.from({ length: count }).map((_, index) => {
        const isFirst = index === 0;
        const isLast = index === count - 1;
        const borderClass = isFirst ? 'border border-gray-200' : 'border border-t-0 border-gray-200';
        const roundingClass = isFirst ? 'rounded-none rounded-b-none' : isLast ? 'rounded-none rounded-b-lg' : 'rounded-none';

        return (
          <Card key={index} className={`p-4 bg-white ${borderClass} ${roundingClass} animate-pulse`}>
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  {/* Chevron placeholder */}
                  <div className="w-4 h-4 bg-gray-200 rounded flex-shrink-0" />
                  {/* Icon placeholder */}
                  <div className="w-5 h-5 bg-gray-200 rounded flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      {/* Title skeleton */}
                      <div className="h-5 bg-gray-200 rounded w-48" />
                      {/* Type badge skeleton */}
                      <div className="h-4 bg-gray-200 rounded w-16" />
                      {/* Connection badges skeleton */}
                      <div className="h-5 bg-gray-200 rounded-full w-20" />
                      <div className="h-5 bg-gray-200 rounded-full w-24" />
                      {Math.random() > 0.5 && <div className="h-5 bg-gray-200 rounded-full w-28" />}
                    </div>
                  </div>
                </div>
                
                {/* Source files skeleton */}
                <div className="mt-2 ml-11">
                  <div className="h-3 bg-gray-200 rounded w-64" />
                </div>
              </div>

              {/* Action buttons skeleton */}
              <div className="flex items-center gap-2 flex-shrink-0">
                <div className="w-8 h-8 bg-gray-200 rounded" />
                <div className="w-8 h-8 bg-gray-200 rounded" />
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

export default function LineageListView({ 
  graphData, 
  activeInsightType,
  filterType: externalFilterType,
  onFilterTypeChange,
  selectedOperations: externalSelectedOperations,
  sortField: externalSortField,
  sortDirection: externalSortDirection,
  onSortChange,
  loading = false,
  selectedNodeIds,
  onClearSelection
}: LineageListViewProps) {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [isComputing, setIsComputing] = useState(false);
  
  // Use external state if provided, otherwise use internal defaults
  const filterType = externalFilterType ?? (() => {
    const hasFiles = graphData.nodes.some(n => n.type === NodeTypes.FILE);
    return hasFiles ? NodeTypes.FILE : 'all';
  })();
  
  const sortField = externalSortField ?? 'impact';
  const sortDirection = externalSortDirection ?? 'desc';
  const selectedOperations = externalSelectedOperations ?? new Set<string>();
  
  // Track when graphData changes to show loading during heavy computation
  useEffect(() => {
    setIsComputing(true);
    // Defer computation to next tick to allow skeleton to render
    const timer = setTimeout(() => {
      setIsComputing(false);
    }, 0);
    return () => clearTimeout(timer);
  }, [graphData]);

  // Auto-filter to table types when table-related insight is active
  useEffect(() => {
    if (activeInsightType && 
        ['tables_only_read', 'tables_never_read', 'most_connected'].includes(activeInsightType) &&
        onFilterTypeChange) {
      // Check if any table nodes exist in the data using standardized utility
      const hasTables = graphData.nodes.some(n => isTableNode(n.type));
      
      if (hasTables) {
        onFilterTypeChange(NodeTypes.TABLE_OR_VIEW);
      }
    }
  }, [activeInsightType, graphData, onFilterTypeChange]);

  // Auto-expand and scroll to selected nodes
  useEffect(() => {
    if (selectedNodeIds && selectedNodeIds.size > 0) {
      // Auto-expand selected nodes
      setExpandedNodes(new Set(selectedNodeIds));
      
      // Scroll to first selected node after a short delay to ensure DOM is ready
      setTimeout(() => {
        const firstSelected = Array.from(selectedNodeIds)[0];
        const element = document.getElementById(`node-${firstSelected}`);
        if (element) {
          element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }, 100);
    }
  }, [selectedNodeIds]);

  const toggleNode = (nodeId: string) => {
    setExpandedNodes(prev => {
      const newSet = new Set(prev);
      if (newSet.has(nodeId)) {
        newSet.delete(nodeId);
      } else {
        newSet.add(nodeId);
      }
      return newSet;
    });
  };

  // Pre-compute all connections once for performance using shared utility
  // This prevents re-calculating connections for every node on every render
  const allConnections = useMemo(() => {
    return computeConnections(graphData, selectedOperations);
  }, [graphData, selectedOperations]);

  // Fast lookup function - O(1) instead of O(n) filtering
  const getConnections = (nodeId: string) => {
    return getConnectionsUtil(nodeId, allConnections);
  };

  // Enrich nodes with connection counts and impact scores using shared utility
  // Handle different semantics for FILE vs TABLE nodes after READS_FROM direction change
  const enrichedNodes = useMemo(() => {
    return enrichNodes(graphData);
  }, [graphData]);

  // Filter and sort nodes
  // This component handles type filtering (for cards), operation filtering, selection filtering, and sorting
  // Note: graphData may contain connected nodes of other types for connection calculations
  const filteredNodes = useMemo(() => {
    let nodes = enrichedNodes;

    // PRIORITY FILTER: If there are selected nodes, show ONLY those nodes
    if (selectedNodeIds && selectedNodeIds.size > 0) {
      nodes = nodes.filter(node => selectedNodeIds.has(node.id));
    } else {
      // Apply type filter to determine which cards to show
      if (filterType !== 'all') {
        nodes = nodes.filter(node => node.type === filterType);
      }
      
      // Only apply operation filter if no nodes are selected
      // Filter by operation - only show nodes that have connections with selected operations
      if (selectedOperations.size > 0) {
        // Build a Set of node IDs that have the selected operations (O(m) instead of O(n*m))
        const nodesWithOperations = new Set<string>();
        graphData.links.forEach(link => {
          if (selectedOperations.has(link.relationship)) {
            nodesWithOperations.add(link.source);
            nodesWithOperations.add(link.target);
          }
        });
        
        // Filter to nodes with operations, but keep type filter applied
        nodes = nodes.filter(node => nodesWithOperations.has(node.id));
      }
    }

    // Sort nodes
    nodes = [...nodes].sort((a, b) => {
      let compareValue = 0;
      switch (sortField) {
        case 'name':
          compareValue = a.name.localeCompare(b.name);
          break;
        case 'type':
          compareValue = a.type.localeCompare(b.type);
          break;
        case 'upstream':
          compareValue = a.upstreamCount - b.upstreamCount;
          break;
        case 'downstream':
          compareValue = a.downstreamCount - b.downstreamCount;
          break;
        case 'impact':
          compareValue = a.impactScore - b.impactScore;
          break;
      }
      return sortDirection === 'asc' ? compareValue : -compareValue;
    });

    return nodes;
  }, [enrichedNodes, sortField, sortDirection, selectedOperations, graphData.links, selectedNodeIds]);

  // Get unique types
  const types = Array.from(new Set(graphData.nodes.map(n => n.type)));

  const handleSort = (field: SortField) => {
    if (onSortChange) {
      if (sortField === field) {
        onSortChange(field, sortDirection === 'asc' ? 'desc' : 'asc');
      } else {
        onSortChange(field, 'desc');
      }
    }
  };

  const exportNodeToCSV = (node: typeof enrichedNodes[0]) => {
    const { upstream, downstream } = getConnections(node.id);
    const rows = [
      ['Node', node.name],
      ['Type', getNodeTypeDisplayName(node.type)],
      ['Migration Risk (Dependents)', node.impactScore.toString()],
      ['Dependencies (Upstream)', node.upstreamCount.toString()],
      ['Dependents (Downstream)', node.downstreamCount.toString()],
      [''],
      ['Upstream Connections'],
      ['Operation', 'Connected Node', 'Type'],
      ...upstream.map(u => [
        getContextualRelationshipLabel({
          relationship: u.relationship,
          viewingNodeType: node.type,
          direction: 'upstream'
        }),
        u.node?.name || 'Unknown',
        u.node?.type ? getNodeTypeDisplayName(u.node.type) : ''
      ]),
      [''],
      ['Downstream Connections'],
      ['Operation', 'Connected Node', 'Type'],
      ...downstream.map(d => [
        getContextualRelationshipLabel({
          relationship: d.relationship,
          viewingNodeType: node.type,
          direction: 'downstream'
        }),
        d.node?.name || 'Unknown',
        d.node?.type ? getNodeTypeDisplayName(d.node.type) : ''
      ])
    ];
    const csv = rows.map(row => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${node.name.replace(/[^a-z0-9]/gi, '_')}_connections.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const copyNodeDetails = (node: typeof enrichedNodes[0]) => {
    const { upstream, downstream } = getConnections(node.id);
    const text = `${node.name} (${getNodeTypeDisplayName(node.type)})
Migration Risk: ${node.impactScore} dependents
Dependencies: ${node.upstreamCount} | Dependents: ${node.downstreamCount}

Upstream Connections:
${upstream.map(u => `  ${getContextualRelationshipLabel({
  relationship: u.relationship,
  viewingNodeType: node.type,
  direction: 'upstream'
})}: ${u.node?.name || 'Unknown'}`).join('\n')}

Downstream Connections:
${downstream.map(d => `  ${getContextualRelationshipLabel({
  relationship: d.relationship,
  viewingNodeType: node.type,
  direction: 'downstream'
})}: ${d.node?.name || 'Unknown'}`).join('\n')}`;
    
    navigator.clipboard.writeText(text);
  };

  return (
    <div className="space-y-0">
      {/* Selection banner */}
      {selectedNodeIds && selectedNodeIds.size > 0 && (
        <Card className="p-3 bg-blue-50 border-2 border-blue-300 mb-4 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-blue-900">
                📌 Viewing {selectedNodeIds.size} selected node{selectedNodeIds.size !== 1 ? 's' : ''}
              </span>
            </div>
            {onClearSelection && (
              <button
                onClick={onClearSelection}
                className="flex items-center space-x-1 px-3 py-1 text-sm text-blue-700 hover:text-blue-900 hover:bg-blue-100 rounded transition-colors"
              >
                <X className="w-4 h-4" />
                <span>Clear Selection</span>
              </button>
            )}
          </div>
        </Card>
      )}
      
      <Card className="p-4 rounded-b-none border-b-0">
        <div className="mb-3">
          <h3 className="font-semibold text-gray-900 mb-2">Lineage List View</h3>
          <p className="text-xs text-gray-600 mb-3">
            <strong>Migration Planning Tip:</strong> Start with objects having <strong>0-2 dependents</strong> (low risk), 
            then progress to higher dependent counts. Objects with many dependents require extensive testing.
          </p>
          {!loading && (
            <div className="text-sm text-gray-600">
              Showing {filteredNodes.length} {filterType !== 'all' ? getNodeTypeDisplayName(filterType) : 'object'}{filteredNodes.length !== 1 ? 's' : ''} • {graphData.links.length} total connections
              {selectedNodeIds && selectedNodeIds.size > 0 
                ? ` • Filtered by selection` 
                : filterType !== 'all'
                  ? ` • ${getNodeTypeDisplayName(filterType)} type filter active`
                  : ''}
              {selectedOperations.size > 0 
                ? ` • ${selectedOperations.size} operation${selectedOperations.size > 1 ? 's' : ''} selected`
                : ''}
              {' • '}Sorted by {sortField === 'impact' ? 'migration risk (highest first)' : sortField}
            </div>
          )}
          {loading && (
            <div className="text-sm text-gray-600 animate-pulse">
              Loading lineage data...
            </div>
          )}
        </div>
      </Card>

      {loading || isComputing ? (
        <ListViewSkeleton count={8} />
      ) : (
        <div className="space-y-0">
        {filteredNodes.map((node, index) => {
          const isExpanded = expandedNodes.has(node.id);
          const isSelected = selectedNodeIds?.has(node.id) || false;
          
          // Get pre-computed connections (fast O(1) lookup)
          const { upstream, downstream, tableConnections, hasConnections } = getConnections(node.id);
          const isFirst = index === 0;
          const isLast = index === filteredNodes.length - 1;
          
          // Determine impact level for color coding (only for the dependents label)
          const impactLevel = node.impactScore > 10 ? 'high' : node.impactScore > 5 ? 'medium' : 'low';
          
          // Border and rounding classes for cohesive connection
          const borderClass = isFirst ? 'border border-gray-200' : 'border border-t-0 border-gray-200';
          const roundingClass = isFirst ? 'rounded-none rounded-b-none' : isLast ? 'rounded-none rounded-b-lg' : 'rounded-none';
          
          // Highlight selected nodes
          const highlightClass = isSelected ? 'ring-2 ring-blue-500 bg-blue-50' : '';

          return (
            <Card 
              key={node.id} 
              id={`node-${node.id}`}
              className={`p-4 hover:shadow-md transition-shadow bg-white ${borderClass} ${roundingClass} ${highlightClass}`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    {hasConnections && (
                      <button
                        onClick={() => toggleNode(node.id)}
                        className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                      >
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4" />
                        ) : (
                          <ChevronRight className="w-4 h-4" />
                        )}
                      </button>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <div className="min-w-0 flex items-center gap-1">
                          <h4 className="font-medium text-gray-900 flex items-center gap-1 truncate" title={node.name}>
                            {truncateFilePath(node.name)}
                            {/* External creation tooltip for tables without CREATE statement */}
                            {(node.properties?.external_creation === true || 
                              node.properties?.tags?.includes('external_creation')) && (
                              <span 
                                className="inline-flex items-center text-orange-500 hover:text-orange-700 transition-colors cursor-help flex-shrink-0"
                                title="⚠️ No CREATE statement found - This table is referenced but never created in any loaded files. It may be pre-existing or externally managed."
                              >
                                <Info className="w-4 h-4" />
                              </span>
                            )}
                          </h4>
                          <span className="text-xs text-gray-500 flex-shrink-0">({getNodeTypeDisplayName(node.type)})</span>
                        </div>
                        
                        {/* Connection count badges */}
                        {hasConnections && (
                          <>
                            {node.type === 'FILE' ? (
                              <>
                                {tableConnections.length > 0 && (
                                  <span 
                                    className="px-2 py-0.5 text-xs font-medium rounded-full bg-purple-100 text-purple-700 whitespace-nowrap flex-shrink-0"
                                    title="Tables/views this file interacts with"
                                  >
                                    {tableConnections.length} Table{tableConnections.length !== 1 ? 's' : ''}
                                  </span>
                                )}
                                {node.upstreamCount > 0 && (
                                  <span 
                                    className="px-2 py-0.5 text-xs font-medium rounded-full bg-blue-100 text-blue-700 whitespace-nowrap flex-shrink-0"
                                    title="Files this file depends on"
                                  >
                                    {node.upstreamCount} File {node.upstreamCount !== 1 ? 'Dependencies' : 'Dependency'}
                                  </span>
                                )}
                                {node.downstreamCount > 0 && (
                                  <span 
                                    className={`px-2 py-0.5 text-xs font-semibold rounded-full whitespace-nowrap flex-shrink-0 ${
                                      impactLevel === 'high' ? 'bg-red-100 text-red-800' :
                                      impactLevel === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                                      'bg-gray-100 text-gray-600'
                                    }`}
                                    title={`${node.downstreamCount} files depend on this - migration risk ${impactLevel}`}
                                  >
                                    {node.downstreamCount} Dependent File{node.downstreamCount !== 1 ? 's' : ''}
                                  </span>
                                )}
                              </>
                            ) : (
                              <>
                                {node.upstreamCount > 0 && (
                                  <span 
                                    className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-700 whitespace-nowrap flex-shrink-0"
                                    title="Files that create/write to this table"
                                  >
                                    {node.upstreamCount} Writer{node.upstreamCount !== 1 ? 's' : ''}
                                  </span>
                                )}
                                {node.downstreamCount > 0 && (
                                  <span 
                                    className={`px-2 py-0.5 text-xs font-semibold rounded-full whitespace-nowrap flex-shrink-0 ${
                                      impactLevel === 'high' ? 'bg-red-100 text-red-800' :
                                      impactLevel === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                                      'bg-blue-100 text-blue-700'
                                    }`}
                                    title={`${node.downstreamCount} files read from this table - impact ${impactLevel}`}
                                  >
                                    {node.downstreamCount} Reader{node.downstreamCount !== 1 ? 's' : ''}
                                  </span>
                                )}
                              </>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  {node.sources.length > 0 && (
                    <div className="mt-2 ml-11 text-xs text-gray-600">
                      <span className="font-medium">Sources:</span>{' '}
                      {node.sources.map((s, idx) => (
                        <span key={idx} title={s.filename}>
                          {truncateFilePath(s.filename)}
                          {idx < node.sources.length - 1 ? ', ' : ''}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Action buttons */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={() => exportNodeToCSV(node)}
                    className="p-1.5 hover:bg-gray-100 rounded text-gray-600 hover:text-gray-900"
                    title="Export to CSV"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => copyNodeDetails(node)}
                    className="p-1.5 hover:bg-gray-100 rounded text-gray-600 hover:text-gray-900"
                    title="Copy details"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Expanded connections with operation breakdown */}
              {isExpanded && hasConnections && (
                <div className="mt-4 ml-11 space-y-3 border-l-2 border-gray-200 pl-4">
                  {/* For FILE nodes, show as "Tables/Views Referenced" instead of "Downstream" */}
                  {node.type === 'FILE' && downstream.length > 0 && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs font-semibold text-gray-700">
                          TABLES/VIEWS REFERENCED ({downstream.length})
                        </p>
                        <div className="flex items-center space-x-2">
                          {Array.from(new Set(downstream.map(d => d.relationship))).map(op => {
                            const count = downstream.filter(d => d.relationship === op).length;
                            const label = getContextualRelationshipLabel({
                              relationship: op,
                              viewingNodeType: node.type,
                              direction: 'downstream'
                            });
                            return (
                              <span key={op} className={`text-xs px-2 py-0.5 rounded ${getRelationshipColor(op)}`}>
                                {label}: {count}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                      <div className="space-y-1 max-h-64 overflow-y-auto">
                        {downstream.map(({ node: downNode, relationship }, idx) => {
                          // Count how many other nodes depend on this table
                          const dependentCount = graphData.links.filter(l => l.source === downNode?.id).length;
                          return (
                          <div key={idx} className="grid grid-cols-[16px_auto_1fr_140px_70px] gap-2 items-center text-sm text-gray-700 py-1 hover:bg-gray-50 px-2 rounded">
                            <GitBranch className="w-3 h-3 text-gray-400" />
                            <span className={`font-mono text-xs px-2 py-0.5 rounded whitespace-nowrap ${getRelationshipColor(relationship)}`}>
                              {getContextualRelationshipLabel({
                                relationship,
                                viewingNodeType: node.type,
                                direction: 'downstream'
                              })}
                            </span>
                            <span className="min-w-0 break-words" title={downNode?.name}>{truncateFilePath(downNode?.name || 'Unknown')}</span>
                            <span className="text-xs text-gray-400 truncate">({downNode?.type ? getNodeTypeDisplayName(downNode.type) : ''})</span>
                            <div className="text-right">
                            {dependentCount > 0 && (
                              <span className="text-xs text-orange-600 font-medium whitespace-nowrap" title={`${dependentCount} other objects depend on this`}>
                                {dependentCount} deps
                              </span>
                            )}
                            </div>
                          </div>
                        )})}
                      </div>
                    </div>
                  )}

                  {/* For non-FILE nodes or show upstream */}
                  {(node.type !== 'FILE' || upstream.length > 0) && upstream.length > 0 && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs font-semibold text-gray-700">
                          {node.type === 'FILE' ? 'DEPENDS ON' : 'UPSTREAM'} ({upstream.length})
                        </p>
                        <div className="flex items-center space-x-2">
                          {Array.from(new Set(upstream.map(u => u.relationship))).map(op => {
                            const count = upstream.filter(u => u.relationship === op).length;
                            const label = getContextualRelationshipLabel({
                              relationship: op,
                              viewingNodeType: node.type,
                              direction: 'upstream'
                            });
                            return (
                              <span key={op} className={`text-xs px-2 py-0.5 rounded ${getRelationshipColor(op)}`}>
                                {label}: {count}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                      <div className="space-y-1 max-h-64 overflow-y-auto">
                        {upstream.map(({ node: upNode, relationship }, idx) => (
                          <div key={idx} className="grid grid-cols-[16px_auto_1fr_140px] gap-2 items-center text-sm text-gray-600 py-1 hover:bg-gray-50 px-2 rounded">
                            <GitBranch className="w-3 h-3 text-blue-500" />
                            <span className={`font-mono text-xs px-2 py-0.5 rounded whitespace-nowrap ${getRelationshipColor(relationship)}`}>
                              {getContextualRelationshipLabel({
                                relationship,
                                viewingNodeType: node.type,
                                direction: 'upstream'
                              })}
                            </span>
                            <span className="min-w-0 break-words" title={upNode?.name}>{truncateFilePath(upNode?.name || 'Unknown')}</span>
                            <span className="text-xs text-gray-400 truncate">({upNode?.type ? getNodeTypeDisplayName(upNode.type) : ''})</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* For TABLE nodes, show downstream */}
                  {node.type !== 'FILE' && downstream.length > 0 && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs font-semibold text-gray-700">
                          DOWNSTREAM ({downstream.length})
                        </p>
                        <div className="flex items-center space-x-2">
                          {Array.from(new Set(downstream.map(d => d.relationship))).map(op => {
                            const count = downstream.filter(d => d.relationship === op).length;
                            const label = getContextualRelationshipLabel({
                              relationship: op,
                              viewingNodeType: node.type,
                              direction: 'downstream'
                            });
                            return (
                              <span key={op} className={`text-xs px-2 py-0.5 rounded ${getRelationshipColor(op)}`}>
                                {label}: {count}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                      <div className="space-y-1 max-h-64 overflow-y-auto">
                        {downstream.map(({ node: downNode, relationship }, idx) => (
                          <div key={idx} className="grid grid-cols-[16px_auto_1fr_140px] gap-2 items-center text-sm text-gray-600 py-1 hover:bg-gray-50 px-2 rounded">
                            <GitBranch className="w-3 h-3 text-green-500" />
                            <span className={`font-mono text-xs px-2 py-0.5 rounded whitespace-nowrap ${getRelationshipColor(relationship)}`}>
                              {getContextualRelationshipLabel({
                                relationship,
                                viewingNodeType: node.type,
                                direction: 'downstream'
                              })}
                            </span>
                            <span className="min-w-0 break-words" title={downNode?.name}>{truncateFilePath(downNode?.name || 'Unknown')}</span>
                            <span className="text-xs text-gray-400 truncate">({downNode?.type ? getNodeTypeDisplayName(downNode.type) : ''})</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </Card>
          );
        })}
        </div>
      )}
    </div>
  );
}

