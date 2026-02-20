'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import dynamic from 'next/dynamic';
import { Card } from '@/components';
import { truncateFilePath } from '@/lib/path-utils';

// Dynamically import CytoscapeGraph component
const CytoscapeGraph = dynamic(() => import('./CytoscapeGraph'), {
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
  upstreamCount?: number;
  downstreamCount?: number;
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

interface LineageGraphViewProps {
  graphData: GraphData | null;
  displayGraphData: GraphData | null;
  loading?: boolean;
  isViewSwitching?: boolean;
  isClearingFilters?: boolean;
  
  // Search/highlight state (passed from container)
  highlightedNodes: Set<string>;
  highlightedLinks: Set<string>;
  nodeRoles: Map<string, 'matched' | 'upstream' | 'downstream'>;
  
  // Selection callbacks
  onNodeSelect?: (nodeIds: Set<string>, nodes: Node[]) => void;
  onClearSelection?: () => void;
  
  // Dimensions
  width?: number;
  height?: number;
}

// Graph skeleton loading component
function GraphSkeleton({ height, message }: { height: number; message?: string }) {
  return (
    <div className="relative bg-gray-900 rounded-lg" style={{ height }}>
      {/* Graph skeleton with animated nodes */}
      <div className="absolute inset-0 flex items-center justify-center p-12">
        <div className="relative w-full h-full">
          {/* Animated node circles scattered across canvas */}
          {[
            { top: '20%', left: '15%', size: 48, delay: '0s' },
            { top: '25%', left: '45%', size: 56, delay: '0.2s' },
            { top: '15%', left: '75%', size: 52, delay: '0.4s' },
            { top: '50%', left: '25%', size: 60, delay: '0.6s' },
            { top: '55%', left: '55%', size: 48, delay: '0.8s' },
            { top: '45%', left: '85%', size: 54, delay: '1s' },
            { top: '75%', left: '20%', size: 50, delay: '1.2s' },
            { top: '80%', left: '50%', size: 56, delay: '1.4s' },
            { top: '70%', left: '80%', size: 52, delay: '1.6s' },
          ].map((node, i) => (
            <div
              key={i}
              className="absolute rounded-full bg-gray-700 animate-pulse"
              style={{
                top: node.top,
                left: node.left,
                width: node.size,
                height: node.size,
                animationDelay: node.delay,
                animationDuration: '2s'
              }}
            />
          ))}
          
          {/* Connecting lines skeleton */}
          <svg className="absolute inset-0 w-full h-full opacity-30">
            <line x1="15%" y1="20%" x2="45%" y2="25%" stroke="#4B5563" strokeWidth="2" />
            <line x1="45%" y1="25%" x2="75%" y2="15%" stroke="#4B5563" strokeWidth="2" />
            <line x1="15%" y1="20%" x2="25%" y2="50%" stroke="#4B5563" strokeWidth="2" />
            <line x1="45%" y1="25%" x2="55%" y2="55%" stroke="#4B5563" strokeWidth="2" />
            <line x1="75%" y1="15%" x2="85%" y2="45%" stroke="#4B5563" strokeWidth="2" />
            <line x1="25%" y1="50%" x2="55%" y2="55%" stroke="#4B5563" strokeWidth="2" />
            <line x1="55%" y1="55%" x2="85%" y2="45%" stroke="#4B5563" strokeWidth="2" />
            <line x1="25%" y1="50%" x2="20%" y2="75%" stroke="#4B5563" strokeWidth="2" />
            <line x1="55%" y1="55%" x2="50%" y2="80%" stroke="#4B5563" strokeWidth="2" />
            <line x1="85%" y1="45%" x2="80%" y2="70%" stroke="#4B5563" strokeWidth="2" />
          </svg>
          
          {/* Loading text */}
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center bg-gray-900 bg-opacity-80 rounded-lg p-4">
              <div className="h-2 w-32 bg-gray-600 rounded animate-pulse mb-2 mx-auto" />
              <p className="text-gray-400 text-sm animate-pulse">
                {message || 'Loading graph view...'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LineageGraphView({
  graphData,
  displayGraphData,
  loading = false,
  isViewSwitching = false,
  isClearingFilters = false,
  highlightedNodes,
  highlightedLinks,
  nodeRoles,
  onNodeSelect,
  onClearSelection,
  width = 1200,
  height = 700,
}: LineageGraphViewProps) {
  // Internal state
  const cyRef = useRef<any>(null);
  const hasInitialFitRef = useRef(false);
  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(new Set());

  // Get node color based on type or role
  const getNodeColor = useCallback((node: Node) => {
    // If node is highlighted, use role-specific color
    if (highlightedNodes.has(node.id)) {
      const role = nodeRoles.get(node.id);
      if (role === 'matched') return '#FCD34D';
      else if (role === 'upstream') return '#3B82F6';
      else if (role === 'downstream') return '#10B981';
    }

    // Check for external creation tag (tables without CREATE statement)
    const isExternalCreation = node.properties?.external_creation === true || 
                               node.properties?.tags?.includes('external_creation');
    
    // Default colors by type
    const type = (node.type || '').toUpperCase();
    
    // Special styling for externally created tables
    if (isExternalCreation && (type === 'TABLE' || type === 'VIEW' || type === 'TABLE_OR_VIEW')) {
      return '#F97316'; // Orange - indicates external/pre-existing table
    }
    
    const colorMap: Record<string, string> = {
      VIEW: '#8B5CF6',
      TABLE: '#10B981',
      TABLE_OR_VIEW: '#10B981',
      SCRIPT: '#3B82F6',
      FILE: '#F59E0B',
      DATABASE: '#EF4444',
      COLUMN: '#EC4899',
    };
    return colorMap[type] || '#6B7280';
  }, [highlightedNodes, nodeRoles]);

  // Get edge color based on relationship type
  const getEdgeColor = useCallback((relationship: string) => {
    const colorMap: Record<string, string> = {
      READS_FROM: '#3B82F6',      // Blue - reading data
      WRITES_TO: '#10B981',       // Green - writing data (INSERT/UPDATE)
      CREATES: '#8B5CF6',         // Purple - creating tables
      CREATES_INDEX: '#A78BFA',   // Light Purple - creating indexes
      DELETES_FROM: '#EF4444',    // Red - destructive operations (DELETE/TRUNCATE)
      DROPS: '#9333EA',           // Dark Purple - metadata destruction (DROP)
      DEPENDS_ON: '#6B7280',      // Gray - generic dependency
    };
    return colorMap[relationship] || '#9CA3AF';
  }, []);

  // Transform graph data to Cytoscape format
  const cytoscapeElements = useMemo(() => {
    if (!displayGraphData) return [];

    const nodes = displayGraphData.nodes.map(node => ({
      data: {
        id: node.id,
        label: truncateFilePath(node.name),
        fullName: node.name,  // Store full name for tooltips and details
        type: node.type,
        color: getNodeColor(node),
        sources: node.sources,
        properties: node.properties,
        isExternalCreation: node.properties?.external_creation === true || 
                           node.properties?.tags?.includes('external_creation'),
      },
    }));

    const edges = displayGraphData.links.map(link => ({
      data: {
        id: `${link.source}-${link.target}`,
        source: link.source,
        target: link.target,
        label: link.relationship,
        relationship: link.relationship,
        color: getEdgeColor(link.relationship),
      },
    }));

    return [...nodes, ...edges];
  }, [displayGraphData, getNodeColor, getEdgeColor]);

  // Cytoscape stylesheet
  const cytoscapeStylesheet = useMemo(() => [
    {
      selector: 'node',
      style: {
        'background-color': 'data(color)',
        'label': 'data(label)',
        'color': '#FFFFFF',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': '11px',
        'font-weight': 'bold',
        'text-outline-width': 2,
        'text-outline-color': '#111827',
        'text-wrap': 'wrap',
        'text-max-width': '120px',
        'text-justification': 'center',
        'border-width': 2,
        'border-color': '#111827',
        'width': 50,
        'height': 50,
        'padding': '8px',
        'transition-property': 'opacity, border-width, border-color',
        'transition-duration': '0.3s',
      },
    },
    {
      selector: 'edge',
      style: {
        'width': 2,
        'line-color': 'data(color)',
        'target-arrow-color': 'data(color)',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'label': 'data(label)',
        'font-size': '10px',
        'color': '#D1D5DB',
        'text-background-color': '#111827',
        'text-background-opacity': 0.8,
        'text-background-padding': '3px',
        'text-rotation': 'autorotate',
        'transition-property': 'opacity, width, line-color',
        'transition-duration': '0.3s',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-width': 4,
        'border-color': '#FCD34D',
      },
    },
    {
      selector: 'edge:selected',
      style: {
        'width': 4,
      },
    },
  ], []);

  // Apply dimming effect for selection
  const applySelectionDimming = useCallback((selectedNodeIds: Set<string>) => {
    if (!cyRef.current || !graphData) return;

    const cy = cyRef.current;
    if (!cy || !cy.elements) return;
    
    // Get connected edges and neighbors
    const connectedEdgeIds = new Set<string>();
    const neighborNodeIds = new Set<string>();
    
    graphData.links.forEach(link => {
      if (selectedNodeIds.has(link.source) || selectedNodeIds.has(link.target)) {
        connectedEdgeIds.add(`${link.source}-${link.target}`);
        neighborNodeIds.add(link.source);
        neighborNodeIds.add(link.target);
      }
    });

    // Dim all elements first
    cy.elements().style('opacity', 0.15);
    
    // Un-dim selected nodes
    selectedNodeIds.forEach(nodeId => {
      cy.getElementById(nodeId).style({
        'opacity': 1.0,
        'border-width': 4,
        'border-color': '#FCD34D',
      });
    });
    
    // Un-dim and highlight connected edges
    connectedEdgeIds.forEach(edgeId => {
      cy.getElementById(edgeId).style({
        'opacity': 1.0,
        'width': 4,
      });
    });
    
    // Un-dim neighbor nodes
    neighborNodeIds.forEach(nodeId => {
      if (!selectedNodeIds.has(nodeId)) {
        cy.getElementById(nodeId).style('opacity', 0.8);
      }
    });
  }, [graphData]);

  // Clear dimming effect
  const clearDimming = useCallback(() => {
    if (!cyRef.current) return;
    
    const cy = cyRef.current;
    if (!cy || !cy.elements) return;
    cy.elements().style({
      'opacity': 1.0,
      'border-width': 2,
      'border-color': '#111827',
      'width': 2,
    });
  }, []);

  // Node click handler for multi-selection
  const handleNodeClick = useCallback((nodeId: string) => {
    if (!graphData) return;

    setSelectedNodes(prev => {
      const newSelection = new Set(prev);
      if (newSelection.has(nodeId)) {
        newSelection.delete(nodeId);
      } else {
        newSelection.add(nodeId);
      }
      
      // Apply dimming effect
      if (newSelection.size > 0) {
        applySelectionDimming(newSelection);
      } else {
        clearDimming();
      }
      
      return newSelection;
    });
  }, [graphData, applySelectionDimming, clearDimming]);

  // Handle background click to clear selection
  const handleBackgroundClick = useCallback(() => {
    setSelectedNodes(new Set());
    clearDimming();
  }, [clearDimming]);

  // Initialize Cytoscape event handlers
  const handleCytoscapeInit = useCallback((cy: any) => {
    if (!cy) {
      console.warn('[LineageGraphView] Cytoscape instance is null');
      return;
    }

    cyRef.current = cy;
    
    console.log('[LineageGraphView] Cytoscape initialized with', cy.nodes().length, 'nodes');

    // Node click event
    cy.on('tap', 'node', (event: any) => {
      if (event && event.target) {
        const nodeId = event.target.id();
        handleNodeClick(nodeId);
      }
    });

    // Background click event
    cy.on('tap', (event: any) => {
      if (event && event.target === cy) {
        handleBackgroundClick();
      }
    });

    // Apply layout with performance optimizations
    const nodeCount = cy.nodes().length;
    const isLargeGraph = nodeCount > 50;

    console.log('[LineageGraphView] Applying layout for', nodeCount, 'nodes (large:', isLargeGraph, ')');
    
    // Smart layout selection - use breadthfirst for large graphs, cose for small
    let layoutConfig: any;
    
    if (isLargeGraph) {
      // For large graphs, use breadthfirst (fast and hierarchical)
      layoutConfig = {
        name: 'breadthfirst',
        animate: false,
        fit: !hasInitialFitRef.current, // Only fit on first load
        padding: 50,
        directed: true,
        spacingFactor: 2.0,  // Increased for better spacing
        avoidOverlap: true,
        nodeDimensionsIncludeLabels: true,  // Account for label size
      };
      console.log('[LineageGraphView] Using breadthfirst layout for performance');
    } else {
      // For small graphs, use cose with reduced iterations
      layoutConfig = {
        name: 'cose',
        animate: true,
        animationDuration: 300,
        fit: !hasInitialFitRef.current, // Only fit on first load
        padding: 50,
        nodeRepulsion: 12000,  // Increased to push nodes apart more
        idealEdgeLength: 150,  // Increased for more space between nodes
        edgeElasticity: 100,
        nestingFactor: 1.2,
        gravity: 1,
        numIter: 300,
        initialTemp: 200,
        coolingFactor: 0.95,
        minTemp: 1.0,
        avoidOverlap: true,  // Prevent node overlap
        nodeDimensionsIncludeLabels: true,  // Account for label size
      };
      console.log('[LineageGraphView] Using cose layout with animation');
    }
    
    try {
      const layout = cy.layout(layoutConfig);
      layout.run();
      
      // Mark that we've done initial fit
      if (!hasInitialFitRef.current) {
        hasInitialFitRef.current = true;
      }
      
      console.log('[LineageGraphView] Layout completed successfully');
    } catch (error) {
      console.error('[LineageGraphView] Layout error:', error);
    }
  }, [handleNodeClick, handleBackgroundClick]);

  // Notify parent of selection changes
  useEffect(() => {
    if (onNodeSelect && selectedNodes.size > 0 && graphData) {
      const selectedNodeData = graphData.nodes.filter(n => selectedNodes.has(n.id));
      
      // Calculate upstream/downstream counts for each selected node
      const nodesWithCounts = selectedNodeData.map(node => {
        if (node.type === 'FILE') {
          // FILES: count file dependencies and table interactions
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
          // TABLES: count files that interact with them
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
      
      onNodeSelect(selectedNodes, nodesWithCounts);
    } else if (onNodeSelect && selectedNodes.size === 0) {
      // Notify parent of empty selection
      onNodeSelect(new Set(), []);
    }
  }, [selectedNodes, graphData, onNodeSelect]);

  // Handle external clear selection
  useEffect(() => {
    if (onClearSelection) {
      // This effect doesn't do anything, but presence of onClearSelection
      // indicates parent can trigger a clear
    }
  }, [onClearSelection]);

  // Render skeleton or graph
  if (loading || isViewSwitching || isClearingFilters) {
    const message = isClearingFilters ? 'Clearing filters...' : 'Loading graph view...';
    return (
      <Card className="overflow-hidden">
        <GraphSkeleton height={height} message={message} />
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      {cytoscapeElements.length > 0 && displayGraphData ? (
        <>
          <div 
            className="bg-gray-900 rounded-lg relative" 
            style={{ width: '100%', height }}
            key={`graph-${displayGraphData.nodes.length}-${displayGraphData.links.length}`}
          >
            <CytoscapeGraph
              key={`cyto-${displayGraphData.nodes.length}-${displayGraphData.links.length}`}
              elements={cytoscapeElements}
              stylesheet={cytoscapeStylesheet}
              onInit={handleCytoscapeInit}
              width={width}
              height={height}
            />
          </div>
          <div className="p-3 bg-white border-t border-gray-200">
            <p className="text-sm text-gray-600 break-words">
              <strong>Controls:</strong> Scroll to zoom • Drag to pan • Click nodes to select • Click background to clear
              {displayGraphData && ` • ${displayGraphData.nodes.length} nodes, ${displayGraphData.links.length} edges`}
              {displayGraphData && displayGraphData.nodes.length > 50 && (
                <> • Layout: {displayGraphData.nodes.length > 100 ? 'Circle' : 'Hierarchical'}</>
              )}
            </p>
          </div>
        </>
      ) : (
        <GraphSkeleton height={height} message="Preparing graph visualization..." />
      )}
    </Card>
  );
}
