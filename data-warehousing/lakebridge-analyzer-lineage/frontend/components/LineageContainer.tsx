'use client';

import { useState, useEffect, useCallback, useMemo, memo, useRef } from 'react';
import { Sparkles, X, AlertCircle, Upload, ArrowUp } from 'lucide-react';
import dynamic from 'next/dynamic';
import api from '@/lib/api';
import type { AggregateLineageResponse, LineageInsightsResponse } from '@/lib/api';
import { getErrorMessage } from '@/lib/utils';
import { truncateFilePath } from '@/lib/path-utils';
import { 
  ErrorMessage, 
  Card, 
  Button, 
  InsightsPanel, 
  SearchLegend,
  NodeDetailPanel
} from '@/components';
import { getNodeTypeDisplayName } from '@/types/nodeTypes';
import { formatOperationName } from '@/types/relationshipLabels';
import { useFilterState } from '@/hooks/useFilterState';
import { useToast } from '@/hooks/useToast';
import FilterToolbar from './FilterToolbar';

// Dynamically import LineageListView for list mode
const LineageListView = dynamic(() => import('./LineageListView'), {
  ssr: false,
});

// Dynamically import LineageGraphView for graph mode
const LineageGraphView = dynamic(() => import('./LineageGraphView'), {
  ssr: false,
});

interface Node {
  id: string;
  name: string;
  type: string;
  val?: number;
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
  value?: number;
  relationship: string;
}

interface GraphData {
  nodes: Node[];
  links: Link[];
}

// Debounce helper
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

interface LineageContainerProps {
  filterNodeId?: string | null;
  onClearFilter?: () => void;
  hasFiles?: boolean;
  onNavigateToFiles?: () => void;
}

function LineageContainer({ filterNodeId, onClearFilter, hasFiles = true, onNavigateToFiles }: LineageContainerProps) {
  // Use filter state hook for persistent, centralized filter management
  const {
    filterState,
    setSearchQuery,
    setNodeTypeFilter,
    setSelectedOperations,
    setSelectedFiles,
    setProgramPattern,
    setObjectPattern,
    setShowFileDependencies,
    setViewMode,
    setSortField,
    setSortDirection,
    resetFilters,
    hasActiveFilters,
    activeFilterCount,
  } = useFilterState();

  // Core data state
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [fullGraphData, setFullGraphData] = useState<GraphData | null>(null);
  const [insights, setInsights] = useState<LineageInsightsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Track if component is ready for external filtering (prevents premature filter application)
  const [isReadyForFiltering, setIsReadyForFiltering] = useState(false);
  const pendingFilterNodeId = useRef<string | null>(null);
  const lastAppliedFilterNodeId = useRef<string | null>(null);
  
  // Track filter changes to show filtering indicator
  const [filterVersion, setFilterVersion] = useState(0);
  const filteringTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Performance metrics
  const [performanceMetrics, setPerformanceMetrics] = useState<{
    apiTime: number;
    backendTime: number;
    cached: boolean;
  } | null>(null);

  // Progressive loading state
  const [visibleNodes, setVisibleNodes] = useState<Set<string>>(new Set());
  const [expansionDepth, setExpansionDepth] = useState<number>(1);

  // Selection state for both views - graph and list have separate state
  const [graphSelectedNodes, setGraphSelectedNodes] = useState<Set<string>>(new Set());
  const [graphDetailPanelNodes, setGraphDetailPanelNodes] = useState<Node[]>([]);
  
  // List view selection (kept for list view specific handling)
  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(new Set());
  const [detailPanelNodes, setDetailPanelNodes] = useState<Node[]>([]);


  // Search state (not persisted)
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [highlightedLinks, setHighlightedLinks] = useState<Set<string>>(new Set());
  const [connectionCount, setConnectionCount] = useState<number>(0);
  const [nodeRoles, setNodeRoles] = useState<Map<string, 'matched' | 'upstream' | 'downstream'>>(new Map());
  const [matchedNodeName, setMatchedNodeName] = useState<string>('');
  const [upstreamCount, setUpstreamCount] = useState<number>(0);
  const [downstreamCount, setDownstreamCount] = useState<number>(0);

  // UI state
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [isViewSwitching, setIsViewSwitching] = useState(false);
  const [isClearingFilters, setIsClearingFilters] = useState(false);
  const [showScrollToTop, setShowScrollToTop] = useState(false);
  const prevViewMode = useRef(filterState.viewMode);
  
  // Toast notifications
  const { showToast } = useToast();

  // Track filter state changes to trigger filtering indicator
  const currentFilterState = useMemo(() => ({
    operations: Array.from(filterState.selectedOperations).sort().join(','),
    programPattern: filterState.programPattern,
    objectPattern: filterState.objectPattern,
    nodeType: filterState.nodeTypeFilter,
    highlightedNodes: highlightedNodes.size,
  }), [filterState.selectedOperations, filterState.programPattern, filterState.objectPattern, filterState.nodeTypeFilter, highlightedNodes]);

  const prevFilterState = useRef(currentFilterState);
  const [isFiltering, setIsFiltering] = useState(false);

  useEffect(() => {
    // Check if filters have changed
    const filterChanged = JSON.stringify(prevFilterState.current) !== JSON.stringify(currentFilterState);
    
    if (filterChanged && graphData) {
      // Show filtering indicator
      setIsFiltering(true);
      
      // Clear any existing timeout
      if (filteringTimeoutRef.current) {
        clearTimeout(filteringTimeoutRef.current);
      }
      
      // Hide indicator after filtering completes (short delay)
      filteringTimeoutRef.current = setTimeout(() => {
        setIsFiltering(false);
      }, 100);
      
      prevFilterState.current = currentFilterState;
    }
    
    return () => {
      if (filteringTimeoutRef.current) {
        clearTimeout(filteringTimeoutRef.current);
      }
    };
  }, [currentFilterState, graphData]);

  // Active insight filter tracking
  const [activeInsightFilter, setActiveInsightFilter] = useState<{
    type: string;
    label: string;
    nodeId?: string;
  } | null>(null);

  // Graph dimensions
  const [graphDimensions, setGraphDimensions] = useState({ width: 1200, height: 700 });

  useEffect(() => {
    if (hasFiles) {
      // Only load if we don't have data yet
      if (!fullGraphData) {
        setIsReadyForFiltering(false);
        loadCompleteLineage();
      } else {
        // Data already exists, mark as ready immediately
        setIsReadyForFiltering(true);
      }
    } else {
      setLoading(false);
      setIsReadyForFiltering(true); // Mark as ready even with no files
    }
    updateGraphDimensions();
    window.addEventListener('resize', updateGraphDimensions);
    return () => window.removeEventListener('resize', updateGraphDimensions);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasFiles]);

  // File dependencies toggle is now instant (no reload needed)
  // Dependencies are pre-computed on backend, we just filter client-side
  useEffect(() => {
    // No API call needed - file dependencies are already in the data
    // The filtering happens in the useMemo below
  }, [filterState.showFileDependencies]);

  // Track view mode changes for skeleton display
  useEffect(() => {
    if (prevViewMode.current !== filterState.viewMode) {
      setIsViewSwitching(true);
      prevViewMode.current = filterState.viewMode;
      
      // Clear switching state after transition
      const timeout = setTimeout(() => {
        setIsViewSwitching(false);
      }, 300);
      
      return () => clearTimeout(timeout);
    }
  }, [filterState.viewMode]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger if user is typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      if (e.key === '/' || (e.ctrlKey && e.key === 'f')) {
        e.preventDefault();
        // Focus search input
        const searchInput = document.querySelector('input[placeholder*="Search"]') as HTMLInputElement;
        if (searchInput) searchInput.focus();
      } else if (e.ctrlKey && e.key === 'k') {
        e.preventDefault();
        setShowAdvancedFilters(prev => !prev);
      } else if (e.key === 'Escape') {
        handleResetAll();
      } else if (e.key === 'g' || e.key === 'G') {
        setViewMode(filterState.viewMode === 'graph' ? 'list' : 'graph');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [filterState.viewMode, setViewMode]);

  // Scroll to top button visibility
  useEffect(() => {
    const handleScroll = () => {
      // Show button when user scrolls down more than 400px
      setShowScrollToTop(window.scrollY > 400);
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({
      top: 0,
      behavior: 'smooth'
    });
  };

  // Note: Removed hard limits on graph size - user can visualize without restrictions
  // Smart layout selection will handle performance automatically

  const updateGraphDimensions = () => {
    const width = Math.min(window.innerWidth - 100, 1600);
    const height = Math.min(window.innerHeight - 400, 800);
    setGraphDimensions({ width, height });
  };

  // Progressive expansion: expand from a node by N hops
  const expandFromNode = useCallback((nodeId: string, depth: number) => {
    if (!fullGraphData) return new Set<string>();

    const nodesToShow = new Set<string>([nodeId]);
    const queue: Array<{ id: string; currentDepth: number }> = [{ id: nodeId, currentDepth: 0 }];
    const visited = new Set<string>([nodeId]);

    while (queue.length > 0) {
      const { id, currentDepth } = queue.shift()!;
      
      if (currentDepth >= depth) continue;

      // Find connected nodes
      fullGraphData.links.forEach(link => {
        if (link.source === id && !visited.has(link.target)) {
          nodesToShow.add(link.target);
          visited.add(link.target);
          queue.push({ id: link.target, currentDepth: currentDepth + 1 });
        }
        if (link.target === id && !visited.has(link.source)) {
          nodesToShow.add(link.source);
          visited.add(link.source);
          queue.push({ id: link.source, currentDepth: currentDepth + 1 });
        }
      });
    }

    return nodesToShow;
  }, [fullGraphData]);

  // Handle filter by specific node IDs
  const handleFilterByNodes = useCallback((nodeIds: string[], meta?: { type: string; label: string }) => {
    if (!fullGraphData || nodeIds.length === 0) return;

    // Check if any of the requested nodes exist in the graph
    const existingNodeIds = nodeIds.filter(id => 
      fullGraphData.nodes.some(n => n.id === id)
    );
    
    if (existingNodeIds.length === 0) {
      console.warn('[LineageContainer] No matching nodes found for filter:', nodeIds);
      showToast('Selected node not found in the graph', 'error');
      return;
    }
    
    if (existingNodeIds.length < nodeIds.length) {
      console.warn('[LineageContainer] Some nodes not found:', {
        requested: nodeIds,
        found: existingNodeIds
      });
    }
    
    // Store filter metadata if provided
    if (meta) {
      setActiveInsightFilter(meta);
    }
    
    // Expand from each existing node
    const allVisibleNodes = new Set<string>();
    existingNodeIds.forEach(nodeId => {
      const expanded = expandFromNode(nodeId, expansionDepth);
      expanded.forEach(id => allVisibleNodes.add(id));
    });

    setVisibleNodes(allVisibleNodes);
    
    // Filter graph data to visible nodes
    const visibleGraphData: GraphData = {
      nodes: fullGraphData.nodes.filter(n => allVisibleNodes.has(n.id)),
      links: fullGraphData.links.filter(l => 
        allVisibleNodes.has(l.source) && allVisibleNodes.has(l.target)
      ),
    };

    setGraphData(visibleGraphData);
  }, [fullGraphData, expansionDepth, expandFromNode, showToast]);

  // Handle filter by single node ID (for most connected clicks)
  const handleFilterByNodeId = useCallback((nodeId: string, meta?: { type: string; label: string }) => {
    if (!fullGraphData) {
      console.warn('[LineageContainer] Cannot filter - data not loaded yet');
      return;
    }
    
    // Check if node exists in the graph
    const nodeExists = fullGraphData.nodes.some(n => n.id === nodeId);
    if (!nodeExists) {
      console.warn('[LineageContainer] Node not found in graph:', nodeId);
      showToast(`Node not found: ${nodeId}`, 'error');
      return;
    }
    
    if (meta) {
      setActiveInsightFilter(meta);
    }
    handleFilterByNodes([nodeId]);
  }, [handleFilterByNodes, fullGraphData, showToast]);
  
  // Handle external filter (from Insights tab)
  useEffect(() => {
    // If no filter, clear tracking and exit
    if (!filterNodeId) {
      pendingFilterNodeId.current = null;
      lastAppliedFilterNodeId.current = null;
      return;
    }
    
    // Skip if we've already applied this exact filter
    if (lastAppliedFilterNodeId.current === filterNodeId) {
      return;
    }
    
    // Store the filter and wait for component to be ready
    if (!isReadyForFiltering || !fullGraphData) {
      pendingFilterNodeId.current = filterNodeId;
      return;
    }
    
    // Apply the filter now
    const applyFilter = () => {
      if (!fullGraphData) return;
      
      // Check if node exists
      const nodeExists = fullGraphData.nodes.some(n => n.id === filterNodeId);
      if (!nodeExists) {
        console.warn('[LineageContainer] Node not found:', filterNodeId);
        showToast(`Node not found: ${filterNodeId}`, 'error');
        lastAppliedFilterNodeId.current = filterNodeId;
        return;
      }
      
      // Call handleFilterByNodes without adding it to deps to avoid circular dependency
      handleFilterByNodes([filterNodeId]);
      lastAppliedFilterNodeId.current = filterNodeId;
      pendingFilterNodeId.current = null;
    };
    
    applyFilter();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterNodeId, fullGraphData, isReadyForFiltering, showToast]);
  
  // Apply pending filter once component is ready
  useEffect(() => {
    if (!isReadyForFiltering || !fullGraphData || !pendingFilterNodeId.current) {
      return;
    }
    
    const pendingId = pendingFilterNodeId.current;
    
    // Skip if already applied
    if (lastAppliedFilterNodeId.current === pendingId) {
      pendingFilterNodeId.current = null;
      return;
    }
    
    // Check if node exists
    const nodeExists = fullGraphData.nodes.some(n => n.id === pendingId);
    if (!nodeExists) {
      console.warn('[LineageContainer] Pending node not found:', pendingId);
      showToast(`Node not found: ${pendingId}`, 'error');
      lastAppliedFilterNodeId.current = pendingId;
      pendingFilterNodeId.current = null;
      return;
    }
    
    // Call handleFilterByNodes without adding it to deps to avoid circular dependency
    handleFilterByNodes([pendingId]);
    lastAppliedFilterNodeId.current = pendingId;
    pendingFilterNodeId.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReadyForFiltering, fullGraphData, showToast]);

  const loadCompleteLineage = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const startTime = performance.now();
      console.log('[LineageContainer] Fetching complete lineage data (graph + insights)...', {
        includeFileDependencies: filterState.showFileDependencies
      });
      
      // NEW: Single API call for both graph and insights
      const response = await api.getAggregateLineageComplete(filterState.showFileDependencies);
      const apiTime = performance.now() - startTime;
      
      console.log('[LineageContainer] Received data:', {
        nodes: response.graph.nodes.length,
        edges: response.graph.edges.length,
        fileDependencyEdges: response.graph.stats?.file_dependency_edges || 0,
        apiTime: `${apiTime.toFixed(1)}ms`,
        backendTime: `${response.graph.compute_time_ms?.toFixed(1)}ms`,
        cached: response.graph.cached
      });
      
      // Store performance metrics
      setPerformanceMetrics({
        apiTime,
        backendTime: response.graph.compute_time_ms || 0,
        cached: response.graph.cached || false,
      });
      
      // Transform to internal format
      const transformedData: GraphData = {
        nodes: response.graph.nodes.map(node => ({
          id: node.id,
          name: node.name,
          type: node.type,
          properties: node.properties,
          sources: node.sources,
          val: 10,
        })),
        links: response.graph.edges.map(edge => ({
          source: edge.source,
          target: edge.target,
          relationship: edge.relationship,
          value: 1,
        })),
      };
      
      console.log('[LineageContainer] Transformed data:', {
        nodes: transformedData.nodes.length,
        links: transformedData.links.length
      });
      
      // Store full graph and insights
      setFullGraphData(transformedData);
      setGraphData(transformedData);
      setInsights(response.insights);
      setVisibleNodes(new Set()); // Empty set means all visible
      
      // Mark component as ready for filtering immediately (no delay needed)
      setIsReadyForFiltering(true);

      // Show performance toast in dev mode
      if (process.env.NODE_ENV === 'development') {
        console.log(`[Performance] Loaded in ${apiTime.toFixed(0)}ms (backend: ${response.graph.compute_time_ms?.toFixed(0)}ms, cached: ${response.graph.cached})`);
      }
    } catch (err) {
      console.error('[LineageContainer] Error loading data:', err);
      setError(getErrorMessage(err));
      setIsReadyForFiltering(false);
    } finally {
      setLoading(false);
    }
  };

  // Reset to show all nodes and clear all filters
  const handleResetAll = useCallback(() => {
    if (!fullGraphData) return;
    
    console.log('[LineageContainer] Resetting to full graph and clearing all filters');
    
    // Show loading state
    setIsClearingFilters(true);
    
    // Clear any pending filter
    pendingFilterNodeId.current = null;
    lastAppliedFilterNodeId.current = null;
    
    // Clear external filter if callback provided
    if (onClearFilter) {
      onClearFilter();
    }
    
    // Use setTimeout to ensure UI updates before heavy operations
    setTimeout(() => {
      // Reset graph state
      setVisibleNodes(new Set());
      setGraphData(fullGraphData);
      
      // Clear search state (not persisted)
      setHighlightedNodes(new Set());
      setHighlightedLinks(new Set());
      setConnectionCount(0);
      setNodeRoles(new Map());
      setMatchedNodeName('');
      setUpstreamCount(0);
      setDownstreamCount(0);
      setActiveInsightFilter(null);
      
      // Reset all persisted filters using hook
      resetFilters();
      
      // Close advanced filters
      setShowAdvancedFilters(false);
      
      // Clear selections for both views
      setSelectedNodes(new Set());
      setDetailPanelNodes([]);
      setGraphSelectedNodes(new Set());
      setGraphDetailPanelNodes([]);
    
      // Call parent's onClearFilter if provided
      if (onClearFilter) {
        onClearFilter();
      }
      
      // Hide loading state and show success toast
      setTimeout(() => {
        setIsClearingFilters(false);
        showToast('All filters cleared', 'success', 3000);
      }, 300); // Short delay to ensure UI updates
    }, 50); // Minimal delay to ensure loading state shows
  }, [fullGraphData, filterState.viewMode, onClearFilter, resetFilters, showToast]);

  const handleSearch = async () => {
    if (!filterState.searchQuery.trim()) {
      setHighlightedNodes(new Set());
      setHighlightedLinks(new Set());
      setConnectionCount(0);
      setNodeRoles(new Map());
      setMatchedNodeName('');
      setUpstreamCount(0);
      setDownstreamCount(0);
      return;
    }

    try {
      const result = await api.searchAggregateLineage(filterState.searchQuery);
      
      if (result.paths.length === 0) {
        alert('No matches found');
        return;
      }

      // Get the first match
      const firstPath = result.paths[0];
      
      // Collect all nodes to highlight
      const nodesToHighlight = new Set<string>([
        firstPath.matched_node.id,
        ...firstPath.upstream_nodes,
        ...firstPath.downstream_nodes,
      ]);

      // Build role map for color-coding
      const roles = new Map<string, 'matched' | 'upstream' | 'downstream'>();
      roles.set(firstPath.matched_node.id, 'matched');
      firstPath.upstream_nodes.forEach(id => roles.set(id, 'upstream'));
      firstPath.downstream_nodes.forEach(id => roles.set(id, 'downstream'));

      // Collect all edges to highlight
      const linksToHighlight = new Set<string>(
        firstPath.affected_edges.map(
          edge => `${edge.source}-${edge.target}`
        )
      );

      setHighlightedNodes(nodesToHighlight);
      setHighlightedLinks(linksToHighlight);
      setConnectionCount(firstPath.connection_count);
      setNodeRoles(roles);
      setMatchedNodeName(firstPath.matched_node.name);
      setUpstreamCount(firstPath.upstream_nodes.length);
      setDownstreamCount(firstPath.downstream_nodes.length);
      
      // Note: Graph view will handle highlighting based on highlightedNodes/nodeRoles props
    } catch (err) {
      alert(`Search failed: ${getErrorMessage(err)}`);
    }
  };

  const handleClearSearch = () => {
    setSearchQuery('');
    setHighlightedNodes(new Set());
    setHighlightedLinks(new Set());
    setConnectionCount(0);
    setNodeRoles(new Map());
    setMatchedNodeName('');
    setUpstreamCount(0);
    setDownstreamCount(0);
  };

  const handleExport = async (format: 'json' | 'graphml' | 'csv') => {
    if (!graphData) return;

    setExporting(true);
    setShowExportMenu(false);

    try {
      if (format === 'json') {
        const dataStr = JSON.stringify(graphData, null, 2);
        downloadFile(dataStr, `aggregate-lineage-${Date.now()}.json`, 'application/json');
      } else if (format === 'graphml') {
        const blob = await api.exportAggregateLineage('graphml');
        downloadBlob(blob, `aggregate-lineage-${Date.now()}.graphml`);
      } else if (format === 'csv') {
        const csvHeader = 'Source,Target,Relationship\n';
        const csvRows = graphData.links.map(link => 
          `"${link.source}","${link.target}","${link.relationship}"`
        ).join('\n');
        const csvContent = csvHeader + csvRows;
        downloadFile(csvContent, `aggregate-lineage-edges-${Date.now()}.csv`, 'text/csv');
      }
    } catch (err) {
      alert(`Export failed: ${getErrorMessage(err)}`);
    } finally {
      setExporting(false);
    }
  };

  const downloadFile = (content: string, filename: string, type: string) => {
    const blob = new Blob([content], { type });
    downloadBlob(blob, filename);
  };

  const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleFilterByFiles = async () => {
    if (filterState.selectedFiles.length === 0) {
      await loadCompleteLineage();
      return;
    }

    try {
      setLoading(true);
      const response = await api.filterAggregateLineage(filterState.selectedFiles);
      
      const transformedData: GraphData = {
        nodes: response.nodes.map(node => ({
          id: node.id,
          name: node.name,
          type: node.type,
          properties: node.properties,
          sources: node.sources,
          val: 10,
        })),
        links: response.edges.map(edge => ({
          source: edge.source,
          target: edge.target,
          relationship: edge.relationship,
          value: 1,
        })),
      };
      
      // Update both full and visible graph
      setFullGraphData(transformedData);
      setGraphData(transformedData);
      setVisibleNodes(new Set()); // Reset to show all
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };


  // Handle background click to clear selection (list view)
  const handleBackgroundClick = useCallback(() => {
    setSelectedNodes(new Set());
    setDetailPanelNodes([]);
  }, []);

  // Clear selection programmatically (list view)
  const handleClearSelection = useCallback(() => {
    setSelectedNodes(new Set());
    setDetailPanelNodes([]);
  }, []);

  // Handle selection from graph view
  const handleGraphNodeSelect = useCallback((nodeIds: Set<string>, nodes: Node[]) => {
    setGraphSelectedNodes(nodeIds);
    setGraphDetailPanelNodes(nodes);
  }, []);

  // Clear graph view selection
  const handleGraphClearSelection = useCallback(() => {
    setGraphSelectedNodes(new Set());
    setGraphDetailPanelNodes([]);
  }, []);

  // Remove a single node from selection (list view)
  const handleRemoveNodeFromSelection = useCallback((nodeId: string) => {
    setSelectedNodes(prev => {
      const newSelection = new Set(prev);
      newSelection.delete(nodeId);
      
      if (graphData) {
        const selectedNodeData = graphData.nodes.filter(n => newSelection.has(n.id));
        const nodesWithCounts = selectedNodeData.map(node => {
          if (node.type === 'FILE') {
            const filesThisDependsOn = graphData.links.filter(l => 
              l.source === node.id && l.relationship === 'DEPENDS_ON_FILE'
            ).length;
            const filesDependingOnThis = graphData.links.filter(l => 
              l.target === node.id && l.relationship === 'DEPENDS_ON_FILE'
            ).length;
            return { 
              ...node, 
              upstreamCount: filesThisDependsOn, 
              downstreamCount: filesDependingOnThis 
            };
          } else {
            const filesWritingTo = graphData.links.filter(l => 
              l.target === node.id && ['CREATES', 'WRITES_TO', 'CREATES_INDEX'].includes(l.relationship)
            ).length;
            const filesReadingFrom = graphData.links.filter(l => 
              l.target === node.id && l.relationship === 'READS_FROM'
            ).length;
            return { 
              ...node, 
              upstreamCount: filesWritingTo, 
              downstreamCount: filesReadingFrom 
            };
          }
        });
        setDetailPanelNodes(nodesWithCounts);
      }
      
      return newSelection;
    });
  }, [graphData]);





  // Extract available operations dynamically from graph data
  const availableOperations = useMemo(() => {
    if (!fullGraphData) return [];
    const ops = new Set(fullGraphData.links.map(l => l.relationship));
    return Array.from(ops).sort();
  }, [fullGraphData]);

  // Extract available types for list view filter
  const availableTypes = useMemo(() => {
    if (!graphData) return [];
    const types = new Set(graphData.nodes.map(n => n.type));
    return Array.from(types).sort();
  }, [graphData]);

  // Calculate node type counts for filter toolbar
  const nodeTypeCounts = useMemo(() => {
    if (!graphData) return {};
    const counts: Record<string, number> = {};
    graphData.nodes.forEach(node => {
      counts[node.type] = (counts[node.type] || 0) + 1;
    });
    return counts;
  }, [graphData]);

  // Apply operation and pattern filters to graph data
  const filteredGraphData = useMemo(() => {
    if (!graphData) return null;
    
    // Start with current graphData (which may already be filtered by insight/search)
    let filteredLinks = graphData.links;
    let filteredNodes = graphData.nodes;
    
    const hasOperationFilter = filterState.selectedOperations.size > 0;
    const hasPatternFilter = filterState.programPattern || filterState.objectPattern;
    const hasSearchFilter = highlightedNodes.size > 0;
    const hasTypeFilter = filterState.nodeTypeFilter !== 'all';

    console.log('[FilteredGraphData] Starting filter:', {
      inputNodes: filteredNodes.length,
      inputLinks: filteredLinks.length,
      hasOperationFilter,
      hasPatternFilter,
      hasSearchFilter,
      hasTypeFilter,
      nodeTypeFilter: filterState.nodeTypeFilter,
      operations: Array.from(filterState.selectedOperations),
      activeInsightFilter: activeInsightFilter?.type
    });

    // Apply search filter - only show nodes from search results
    if (hasSearchFilter) {
      const beforeNodes = filteredNodes.length;
      filteredNodes = filteredNodes.filter(n => highlightedNodes.has(n.id));
      
      // Filter links to only include those in the highlighted set
      filteredLinks = filteredLinks.filter(l => {
        const linkKey = `${l.source}-${l.target}`;
        return highlightedLinks.has(linkKey);
      });
      
      console.log('[FilteredGraphData] After search filter:', {
        nodes: filteredNodes.length,
        links: filteredLinks.length,
        removedNodes: beforeNodes - filteredNodes.length
      });
    }

    // Apply node type filter - Show only nodes of selected type, but keep their cross-type connections
    if (hasTypeFilter) {
      const beforeNodes = filteredNodes.length;
      const beforeLinks = filteredLinks.length;
      filteredNodes = filteredNodes.filter(n => n.type === filterState.nodeTypeFilter);
      

      
      // Keep edges where AT LEAST ONE end is a filtered node (preserves cross-type connections)
      const filteredNodeIds = new Set(filteredNodes.map(n => n.id));
      filteredLinks = filteredLinks.filter(l => 
        filteredNodeIds.has(l.source) || filteredNodeIds.has(l.target)
      );
      
      // Add connected nodes back so links have both endpoints
      const connectedNodeIds = new Set<string>();
      filteredLinks.forEach(link => {
        connectedNodeIds.add(link.source);
        connectedNodeIds.add(link.target);
      });
      
      // Add any missing connected nodes (other types) back to the node list
      const missingNodes = graphData.nodes.filter(n => 
        connectedNodeIds.has(n.id) && !filteredNodeIds.has(n.id)
      );
      filteredNodes = [...filteredNodes, ...missingNodes];
      

    }

    // Apply operation filter
    if (hasOperationFilter) {
      const beforeLinks = filteredLinks.length;
      filteredLinks = filteredLinks.filter(l => filterState.selectedOperations.has(l.relationship));
      console.log('[FilteredGraphData] After operation filter:', {
        links: filteredLinks.length,
        removed: beforeLinks - filteredLinks.length
      });
    }

    // Apply pattern filters
    if (hasPatternFilter) {
      const programRegex = filterState.programPattern ? new RegExp(filterState.programPattern, 'i') : null;
      const objectRegex = filterState.objectPattern ? new RegExp(filterState.objectPattern, 'i') : null;

      const matchingNodeIds = new Set<string>();
      
      filteredNodes.forEach(node => {
        const matchesProgram = !programRegex || programRegex.test(node.name);
        const matchesObject = !objectRegex || objectRegex.test(node.name);
        
        if (matchesProgram && matchesObject) {
          matchingNodeIds.add(node.id);
        }
      });

      const beforeNodes = filteredNodes.length;
      // Filter nodes to matching ones
      filteredNodes = filteredNodes.filter(n => matchingNodeIds.has(n.id));
      
      // Filter links to only include those connected to matching nodes
      filteredLinks = filteredLinks.filter(l => 
        matchingNodeIds.has(l.source) && matchingNodeIds.has(l.target)
      );
      
      console.log('[FilteredGraphData] After pattern filter:', {
        nodes: filteredNodes.length,
        removedNodes: beforeNodes - filteredNodes.length
      });
    }

    // After operation/pattern filter, ensure nodes are only those connected by filtered links
    if (hasOperationFilter || hasPatternFilter) {
      const connectedNodeIds = new Set<string>();
      filteredLinks.forEach(link => {
        connectedNodeIds.add(link.source);
        connectedNodeIds.add(link.target);
      });
      
      const beforeNodes = filteredNodes.length;
      filteredNodes = filteredNodes.filter(n => connectedNodeIds.has(n.id));
      
      console.log('[FilteredGraphData] After connected nodes filter:', {
        nodes: filteredNodes.length,
        removedNodes: beforeNodes - filteredNodes.length
      });
    }

    console.log('[FilteredGraphData] Final result:', {
      nodes: filteredNodes.length,
      links: filteredLinks.length
    });

    return {
      nodes: filteredNodes,
      links: filteredLinks
    };
  }, [graphData, filterState.selectedOperations, filterState.programPattern, filterState.objectPattern, activeInsightFilter, highlightedNodes, highlightedLinks, filterState.nodeTypeFilter, fullGraphData]);

  // Use filtered graph data for visualization
  const displayGraphData = filteredGraphData || graphData;

  const availableFiles = useMemo(() => {
    if (!graphData) return [];
    const filesMap = new Map<string, { file_id: string; filename: string }>();
    
    graphData.nodes.forEach(node => {
      node.sources.forEach(source => {
        if (!filesMap.has(source.file_id)) {
          filesMap.set(source.file_id, {
            file_id: source.file_id,
            filename: source.filename,
          });
        }
      });
    });
    
    return Array.from(filesMap.values());
  }, [graphData]);


  // Cached node lookup for filter banner (O(1) instead of repeated O(n) finds)
  // IMPORTANT: This MUST be before ALL early returns to maintain consistent hook order
  const filteredNodeName = useMemo(() => {
    if (!filterNodeId || !graphData) return null;
    const node = graphData.nodes.find(n => n.id === filterNodeId);
    return node?.name || filterNodeId;
  }, [filterNodeId, graphData]);

  // Full-page skeleton for initial load
  if (loading && !graphData) {
    return (
      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          {/* Filter Toolbar Skeleton */}
          <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3 animate-pulse">
            <div className="flex items-center gap-2 flex-wrap">
              {/* Search bar skeleton */}
              <div className="flex-1 min-w-[300px] h-10 bg-gray-200 rounded-lg" />
              {/* Filter buttons skeleton */}
              <div className="h-10 w-32 bg-gray-200 rounded-lg" />
              <div className="h-10 w-28 bg-gray-200 rounded-lg" />
              <div className="h-10 w-24 bg-gray-200 rounded-lg" />
              <div className="h-10 w-20 bg-gray-200 rounded-lg" />
              <div className="h-10 w-24 bg-gray-200 rounded-lg" />
              <div className="h-10 w-20 bg-gray-200 rounded-lg" />
            </div>
          </div>

          {/* Main Content Skeleton - Matches list view */}
          <Card className="p-4 rounded-b-none border-b-0">
            <div className="mb-3">
              <div className="h-5 bg-gray-200 rounded w-40 mb-2" />
              <div className="h-3 bg-gray-200 rounded w-full mb-1" />
              <div className="h-3 bg-gray-200 rounded w-3/4 mb-3" />
              <div className="h-4 bg-gray-200 rounded w-96" />
            </div>
          </Card>

          {/* List items skeleton */}
          <div className="space-y-0">
            {Array.from({ length: 6 }).map((_, index) => {
              const isFirst = index === 0;
              const isLast = index === 5;
              const borderClass = isFirst ? 'border border-gray-200' : 'border border-t-0 border-gray-200';
              const roundingClass = isFirst ? 'rounded-none rounded-b-none' : isLast ? 'rounded-none rounded-b-lg' : 'rounded-none';

              return (
                <Card key={index} className={`p-4 bg-white ${borderClass} ${roundingClass} animate-pulse`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <div className="w-4 h-4 bg-gray-200 rounded flex-shrink-0" />
                        <div className="w-5 h-5 bg-gray-200 rounded flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <div className="h-5 bg-gray-200 rounded w-48" />
                            <div className="h-4 bg-gray-200 rounded w-16" />
                            <div className="h-5 bg-gray-200 rounded-full w-20" />
                            <div className="h-5 bg-gray-200 rounded-full w-24" />
                            {Math.random() > 0.5 && <div className="h-5 bg-gray-200 rounded-full w-28" />}
                          </div>
                        </div>
                      </div>
                      <div className="mt-2 ml-11">
                        <div className="h-3 bg-gray-200 rounded w-64" />
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <div className="w-8 h-8 bg-gray-200 rounded" />
                      <div className="w-8 h-8 bg-gray-200 rounded" />
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>
        </div>

        {/* Sidebar Skeleton */}
        <div className="lg:col-span-1 space-y-4">
          {/* Controls card skeleton */}
          <Card className="p-4 space-y-3 animate-pulse">
            <div className="space-y-2">
              <div className="h-4 bg-gray-200 rounded w-48" />
              <div className="h-3 bg-gray-200 rounded w-40" />
            </div>
          </Card>

          {/* Insights panel skeleton */}
          <Card className="p-4 animate-pulse">
            <div className="h-5 bg-gray-200 rounded w-32 mb-4" />
            <div className="space-y-3">
              {[1, 2, 3].map(i => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="h-4 bg-gray-200 rounded w-40 mb-2" />
                  <div className="h-3 bg-gray-200 rounded w-20" />
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    );
  }

  if (error && !graphData) {
    return (
      <Card>
        <ErrorMessage message={error} />
        <Button onClick={loadCompleteLineage} className="mt-4">
          Retry
        </Button>
      </Card>
    );
  }

  // Empty state for first-time users (no files)
  if (!hasFiles && !loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Card className="max-w-2xl w-full text-center p-12">
          <div className="flex justify-center mb-6">
            <div className="w-24 h-24 rounded-full bg-gradient-to-br from-blue-100 to-purple-100 flex items-center justify-center">
              <Sparkles className="w-12 h-12 text-blue-600" />
            </div>
          </div>
          
          <h2 className="text-3xl font-bold text-gray-900 mb-4">
            No Lineage Data Yet
          </h2>
          
          <p className="text-lg text-gray-600 mb-8 max-w-lg mx-auto">
            Upload analyzer files to visualize your data lineage and understand 
            how your data flows through your ETL pipelines.
          </p>

          <Button
            onClick={onNavigateToFiles}
            size="lg"
            className="mx-auto"
          >
            <Upload className="w-5 h-5 mr-2" />
            Go to Files Tab
          </Button>
        </Card>
      </div>
    );
  }

  // Empty state when files exist but no lineage data (shouldn't happen normally)
  if (!graphData || graphData.nodes.length === 0) {
    return (
      <Card>
        <div className="text-center py-12 text-gray-500">
          <Sparkles className="w-16 h-16 mx-auto mb-4 text-gray-300" />
          <p className="text-lg font-medium">No lineage data yet</p>
          <p className="text-sm mt-2">
            Upload files in the Files tab to see your aggregate lineage graph
          </p>
        </div>
      </Card>
    );
  }

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      {/* Main Graph Area */}
      <div className="lg:col-span-2 space-y-4">
        {/* Pending Filter Loading Banner */}
        {filterNodeId && !isReadyForFiltering && (
          <Card className="p-4 bg-blue-50 border-2 border-blue-300 animate-pulse">
            <div className="flex items-center gap-3">
              <svg className="animate-spin h-5 w-5 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span className="text-sm font-semibold text-blue-900">
                Preparing to filter view...
              </span>
            </div>
          </Card>
        )}
        
        {/* Active Filter Banner */}
        {(filterNodeId || activeInsightFilter) && graphData && isReadyForFiltering && (
          <Card className="p-4 bg-blue-50 border-2 border-blue-300">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-sm font-semibold text-blue-900 flex-shrink-0">
                  {filterNodeId ? "Filtered to connections for:" : "Filtered to:"}
                </span>
                <span className="text-sm text-blue-700 font-mono break-words min-w-0" title={filterNodeId ? filteredNodeName || filterNodeId : activeInsightFilter?.label}>
                  {filterNodeId 
                    ? truncateFilePath(filteredNodeName || filterNodeId)
                    : activeInsightFilter?.label
                  }
                </span>
              </div>
              <button
                onClick={() => {
                  // Clear the insight filter and reset to full graph
                  setActiveInsightFilter(null);
                  setVisibleNodes(new Set());
                  if (fullGraphData) {
                    setGraphData(fullGraphData);
                  }
                  // Call parent's clear filter
                  if (onClearFilter) onClearFilter();
                }}
                className="flex items-center space-x-1 px-3 py-1 text-sm text-blue-700 hover:text-blue-900 hover:bg-blue-100 rounded transition-colors flex-shrink-0"
              >
                <X className="w-4 h-4" />
                <span>Clear Filter</span>
              </button>
            </div>
          </Card>
        )}

        {/* NEW: Filter Toolbar - Always Visible */}
        <FilterToolbar
          searchQuery={filterState.searchQuery}
          onSearchChange={setSearchQuery}
          onSearchSubmit={handleSearch}
          onSearchClear={handleClearSearch}
          nodeTypeFilter={filterState.nodeTypeFilter}
          availableTypes={availableTypes}
          nodeTypeCounts={nodeTypeCounts}
          onNodeTypeChange={setNodeTypeFilter}
          selectedOperations={filterState.selectedOperations}
          availableOperations={availableOperations}
          onOperationsChange={setSelectedOperations}
          selectedFiles={filterState.selectedFiles}
          availableFiles={availableFiles}
          onFilesChange={setSelectedFiles}
          onApplyFileFilter={handleFilterByFiles}
          viewMode={filterState.viewMode}
          onViewModeChange={setViewMode}
          onExport={handleExport}
          exporting={exporting}
          hasActiveFilters={hasActiveFilters}
          onClearAll={handleResetAll}
          showAdvancedFilters={showAdvancedFilters}
          onToggleAdvancedFilters={() => setShowAdvancedFilters(!showAdvancedFilters)}
          activeFilterCount={activeFilterCount}
        />

        {/* Search Legend - Show when search is active */}
        {connectionCount > 0 && (
          <Card className="p-3">
            <SearchLegend
              visible={true}
              matchedNodeName={matchedNodeName}
              upstreamCount={upstreamCount}
              downstreamCount={downstreamCount}
            />
          </Card>
        )}

        {/* Advanced Filters Panel - Collapsible */}
        {showAdvancedFilters && (
          <Card className="p-4">
            <div className="space-y-4">
              {/* Pattern Filters */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-semibold text-gray-900">Name Patterns</h4>
                  {(filterState.programPattern || filterState.objectPattern) && (
                    <button
                      onClick={() => {
                        setProgramPattern('');
                        setObjectPattern('');
                      }}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      Clear
                    </button>
                  )}
                </div>
                <div className="space-y-2">
                  <input
                    type="text"
                    placeholder="Program pattern (regex)..."
                    value={filterState.programPattern}
                    onChange={(e) => setProgramPattern(e.target.value)}
                    className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-900 bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  <input
                    type="text"
                    placeholder="Object pattern (regex)..."
                    value={filterState.objectPattern}
                    onChange={(e) => setObjectPattern(e.target.value)}
                    className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-900 bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                </div>
              </div>

              {/* Filter Summary */}
              {(filterState.selectedOperations.size > 0 || filterState.programPattern || filterState.objectPattern || filterState.nodeTypeFilter !== 'all') && displayGraphData && (
                <div className="pt-3 border-t border-gray-200">
                  <p className="text-sm text-gray-700">
                    <strong>Filtered:</strong> {displayGraphData.nodes.length} nodes, {displayGraphData.links.length} edges
                    {filterState.nodeTypeFilter !== 'all' && ` • Type: ${getNodeTypeDisplayName(filterState.nodeTypeFilter)}`}
                  </p>
                </div>
              )}
            </div>
          </Card>
        )}

        {/* Graph or List View */}
        {isFiltering && (
          <div className="fixed top-20 right-6 z-50 bg-blue-600 text-white px-4 py-2 rounded-lg shadow-lg flex items-center space-x-2 animate-fade-in">
            <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span className="text-sm font-medium">Applying filters...</span>
          </div>
        )}
        {isClearingFilters && (
          <div className="fixed top-20 right-6 z-50 bg-orange-600 text-white px-4 py-2 rounded-lg shadow-lg flex items-center space-x-2 animate-fade-in">
            <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span className="text-sm font-medium">Clearing filters...</span>
          </div>
        )}
        {filterState.viewMode === 'list' ? (
          <LineageListView 
            graphData={displayGraphData || graphData} 
            activeInsightType={activeInsightFilter?.type}
            filterType={filterState.nodeTypeFilter}
            onFilterTypeChange={setNodeTypeFilter}
            selectedOperations={filterState.selectedOperations}
            sortField={filterState.sortField}
            sortDirection={filterState.sortDirection}
            onSortChange={(field, direction) => {
              setSortField(field);
              setSortDirection(direction);
            }}
            loading={loading || isFiltering || isClearingFilters}
            selectedNodeIds={selectedNodes}
            onClearSelection={handleClearSelection}
          />
        ) : (
          <LineageGraphView
            graphData={graphData}
            displayGraphData={displayGraphData}
            loading={loading}
            isViewSwitching={isViewSwitching}
            isClearingFilters={isClearingFilters}
            highlightedNodes={highlightedNodes}
            highlightedLinks={highlightedLinks}
            nodeRoles={nodeRoles}
            onNodeSelect={handleGraphNodeSelect}
            onClearSelection={handleGraphClearSelection}
            width={graphDimensions.width}
            height={graphDimensions.height}
          />
        )}
      </div>

      {/* Sidebar */}
      <div className="lg:col-span-1 space-y-4">
        {/* View Mode & File Dependencies Toggle */}
        <Card className="p-4 space-y-3">
          {/* File Dependencies Toggle - Instant (no reload) */}
          <div className="space-y-2">
            <label className="flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={filterState.showFileDependencies}
                onChange={(e) => setShowFileDependencies(e.target.checked)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 mr-2"
              />
              <span className="text-sm text-gray-700 font-medium">Show File Dependencies</span>
            </label>
            <p className="text-xs text-gray-500">
              FILE→FILE edges (instant toggle - pre-computed)
            </p>
          </div>
          
          {/* Performance Metrics - Show in dev mode */}
          {performanceMetrics && process.env.NODE_ENV === 'development' && (
            <div className="text-xs text-gray-600 space-y-1 pt-2 border-t border-gray-200">
              <p><strong>Performance:</strong></p>
              <p>• API: {performanceMetrics.apiTime.toFixed(0)}ms</p>
              <p>• Backend: {performanceMetrics.backendTime.toFixed(0)}ms</p>
              <p>• Cached: {performanceMetrics.cached ? 'Yes ✓' : 'No'}</p>
            </div>
          )}
        </Card>

        {/* Node Detail Panel - Show for whichever view has selections */}
        {(filterState.viewMode === 'list' ? detailPanelNodes : graphDetailPanelNodes).length > 0 && (
          <NodeDetailPanel
            nodes={filterState.viewMode === 'list' ? detailPanelNodes : graphDetailPanelNodes}
            onRemoveNode={filterState.viewMode === 'list' ? handleRemoveNodeFromSelection : (nodeId) => {
              // Handle graph view node removal
              const newSelection = new Set(graphSelectedNodes);
              newSelection.delete(nodeId);
              if (graphData) {
                const selectedNodeData = graphData.nodes.filter(n => newSelection.has(n.id));
                const nodesWithCounts = selectedNodeData.map(node => {
                  if (node.type === 'FILE') {
                    const filesThisDependsOn = graphData.links.filter(l => 
                      l.source === node.id && l.relationship === 'DEPENDS_ON_FILE'
                    ).length;
                    const filesDependingOnThis = graphData.links.filter(l => 
                      l.target === node.id && l.relationship === 'DEPENDS_ON_FILE'
                    ).length;
                    return { 
                      ...node, 
                      upstreamCount: filesThisDependsOn, 
                      downstreamCount: filesDependingOnThis 
                    };
                  } else {
                    const filesWritingTo = graphData.links.filter(l => 
                      l.target === node.id && ['CREATES', 'WRITES_TO', 'CREATES_INDEX'].includes(l.relationship)
                    ).length;
                    const filesReadingFrom = graphData.links.filter(l => 
                      l.target === node.id && l.relationship === 'READS_FROM'
                    ).length;
                    return { 
                      ...node, 
                      upstreamCount: filesWritingTo, 
                      downstreamCount: filesReadingFrom 
                    };
                  }
                });
                handleGraphNodeSelect(newSelection, nodesWithCounts);
              }
            }}
            onClearAll={filterState.viewMode === 'list' ? handleClearSelection : handleGraphClearSelection}
          />
        )}
        
        {/* Insights Panel */}
        <InsightsPanel 
          insights={insights} 
          loading={loading}
          onFilterByNodes={handleFilterByNodes}
          onFilterByNodeId={handleFilterByNodeId}
          visibleNodeIds={visibleNodes}
          graphData={graphData}
          activeInsightFilter={activeInsightFilter}
        />

        {/* Scroll to Top Button */}
        {showScrollToTop && (
          <button
            onClick={scrollToTop}
            className="fixed bottom-8 right-8 z-50 p-3 bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-lg transition-all duration-300 hover:scale-110 hover:shadow-xl animate-fade-in"
            aria-label="Scroll to top"
            title="Scroll to top"
          >
            <ArrowUp className="w-6 h-6" />
          </button>
        )}
      </div>
    </div>
  );
}

// Export memoized version for better performance
export default memo(LineageContainer);
