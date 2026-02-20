/**
 * Shared utilities for lineage data processing
 * Used by both LineageContainer and LineageListView to avoid code duplication
 */

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

interface Connection {
  nodeId: string;
  node: Node | undefined;
  relationship: string;
}

interface ConnectionMap {
  upstream: Connection[];
  downstream: Connection[];
  tableConnections: Link[];
  hasConnections: boolean;
}

interface EnrichedNode extends Node {
  upstreamCount: number;
  downstreamCount: number;
  impactScore: number;
  tableDependencies?: number;
}

/**
 * Pre-compute all node connections for performance
 * This prevents re-calculating connections for every node on every render
 * 
 * @param graphData - The graph data containing nodes and links
 * @param selectedOperations - Optional set of operations to filter by
 * @returns Map of node IDs to their connection information
 */
export function computeConnections(
  graphData: GraphData,
  selectedOperations?: Set<string>
): Map<string, ConnectionMap> {
  // Create a fast O(1) node lookup map first to avoid O(n²) complexity
  const nodeMap = new Map(graphData.nodes.map(n => [n.id, n]));
  
  const connectionsMap = new Map<string, ConnectionMap>();
  
  graphData.nodes.forEach(node => {
    let upstream: Connection[];
    let downstream: Connection[];
    
    // Use data flow semantics instead of graph topology
    if (node.type === 'TABLE' || node.type === 'TABLE_OR_VIEW' || node.type === 'VIEW') {
      // For TABLES: data flow perspective
      // Upstream = files that WRITE to this table (data producers)
      upstream = graphData.links
        .filter(l => l.target === node.id && 
          ['CREATES', 'WRITES_TO', 'CREATES_INDEX', 'DELETES_FROM', 'DROPS'].includes(l.relationship))
        .map(l => ({
          nodeId: l.source,
          node: nodeMap.get(l.source), // O(1) lookup instead of O(n) find
          relationship: l.relationship
        }));
      
      // Downstream = files that READ from this table (data consumers)
      downstream = graphData.links
        .filter(l => l.target === node.id && 
          ['READS_FROM', 'READS'].includes(l.relationship))
        .map(l => ({
          nodeId: l.source,
          node: nodeMap.get(l.source), // O(1) lookup instead of O(n) find
          relationship: l.relationship
        }));
    } else {
      // For FILES: keep topology-based (which maps to data flow correctly)
      // Upstream = tables this file reads from (dependencies)
      upstream = graphData.links
        .filter(l => l.source === node.id && 
          ['READS_FROM', 'READS'].includes(l.relationship))
        .map(l => ({
          nodeId: l.target,
          node: nodeMap.get(l.target), // O(1) lookup instead of O(n) find
          relationship: l.relationship
        }));
      
      // Downstream = tables this file writes to (outputs)
      downstream = graphData.links
        .filter(l => l.source === node.id && 
          !['READS_FROM', 'READS', 'DEPENDS_ON_FILE'].includes(l.relationship))
        .map(l => ({
          nodeId: l.target,
          node: nodeMap.get(l.target), // O(1) lookup instead of O(n) find
          relationship: l.relationship
        }));
    }

    // Apply operation filter if any operations are selected
    if (selectedOperations && selectedOperations.size > 0) {
      upstream = upstream.filter(c => selectedOperations.has(c.relationship));
      downstream = downstream.filter(c => selectedOperations.has(c.relationship));
    }

    // Pre-compute table connections for FILE nodes
    const tableConnections = node.type === 'FILE' 
      ? graphData.links.filter(l => l.source === node.id && l.relationship !== 'DEPENDS_ON_FILE')
      : [];

    const hasConnections = upstream.length > 0 || downstream.length > 0 || tableConnections.length > 0;

    connectionsMap.set(node.id, { upstream, downstream, tableConnections, hasConnections });
  });

  return connectionsMap;
}

/**
 * Enrich nodes with connection counts and impact scores
 * Handles different semantics for FILE vs TABLE nodes
 * 
 * @param graphData - The graph data containing nodes and links
 * @returns Array of enriched nodes with computed metrics
 */
export function enrichNodes(graphData: GraphData): EnrichedNode[] {
  // Build fast O(1) lookup indexes for links by source and target
  // This avoids O(n*m) complexity by pre-grouping links
  const linksBySource = new Map<string, Link[]>();
  const linksByTarget = new Map<string, Link[]>();
  
  graphData.links.forEach(link => {
    // Group by source
    if (!linksBySource.has(link.source)) {
      linksBySource.set(link.source, []);
    }
    linksBySource.get(link.source)!.push(link);
    
    // Group by target
    if (!linksByTarget.has(link.target)) {
      linksByTarget.set(link.target, []);
    }
    linksByTarget.get(link.target)!.push(link);
  });
  
  return graphData.nodes.map(node => {
    const outgoingLinks = linksBySource.get(node.id) || [];
    const incomingLinks = linksByTarget.get(node.id) || [];
    
    if (node.type === 'FILE') {
      // FILES are always sources (FILE -> TABLE edges)
      // Count tables/objects they interact with
      const tablesDependedOn = outgoingLinks.length;
      
      // Count files that depend on this file (via DEPENDS_ON_FILE relationship)
      const filesDependingOnThis = incomingLinks.filter(l => 
        l.relationship === 'DEPENDS_ON_FILE'
      ).length;
      
      // Count files this file depends on
      const filesThisDependsOn = outgoingLinks.filter(l => 
        l.relationship === 'DEPENDS_ON_FILE'
      ).length;
      
      return {
        ...node,
        upstreamCount: filesThisDependsOn,  // Files this depends on
        downstreamCount: filesDependingOnThis,  // Files that depend on this
        impactScore: filesDependingOnThis,  // Migration risk = files depending on this
        tableDependencies: tablesDependedOn,  // Tables this file interacts with
      };
    } else {
      // TABLES are targets (FILE -> TABLE edges)
      // Count files that read from/write to them
      const filesReadingFrom = incomingLinks.filter(l => 
        l.relationship === 'READS_FROM'
      ).length;
      
      const filesWritingTo = incomingLinks.filter(l => 
        ['CREATES', 'WRITES_TO', 'CREATES_INDEX'].includes(l.relationship)
      ).length;
      
      return {
        ...node,
        upstreamCount: filesWritingTo,  // Files that create/write to this table
        downstreamCount: filesReadingFrom,  // Files that read from this table
        impactScore: filesReadingFrom + filesWritingTo,  // Total interactions
      };
    }
  });
}

/**
 * Calculate impact score for a single node
 * This represents how many objects depend on this node - the "blast radius" if it breaks
 * 
 * @param nodeId - The ID of the node to calculate impact for
 * @param graphData - The graph data containing nodes and links
 * @returns The impact score (number of downstream dependencies)
 */
export function calculateImpactScore(nodeId: string, graphData: GraphData): number {
  const downstream = graphData.links.filter(l => l.source === nodeId).length;
  return downstream; // Only count downstream - what depends on this
}

/**
 * Get connections for a specific node from the connections map
 * 
 * @param nodeId - The ID of the node to get connections for
 * @param connectionsMap - The pre-computed connections map
 * @returns The connection information for the node
 */
export function getConnections(
  nodeId: string,
  connectionsMap: Map<string, ConnectionMap>
): ConnectionMap {
  return connectionsMap.get(nodeId) || { 
    upstream: [], 
    downstream: [], 
    tableConnections: [],
    hasConnections: false 
  };
}
