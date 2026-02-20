/**
 * Contextual Relationship Labels - Transform technical relationship names based on viewing context.
 * 
 * The lineage graph stores relationships from a technical/graph perspective, but they need
 * to be displayed differently depending on which node the user is viewing.
 * 
 * Edge Direction: FILE -> TABLE (file is source, table is target) for all operations
 * 
 * DATA FLOW PERSPECTIVE:
 * 
 * Example 1: "READS_FROM" relationship (FILE --READS_FROM--> TABLE)
 * - From FILE perspective: Table is UPSTREAM (dependency) → "Reads From" 
 *   (File depends on table's data, data flows FROM table TO file)
 * - From TABLE perspective: File is DOWNSTREAM (consumer) → "Read By"
 *   (File consumes table's data, data flows FROM table TO file)
 * 
 * Example 2: "WRITES_TO" relationship (FILE --WRITES_TO--> TABLE)
 * - From FILE perspective: Table is DOWNSTREAM (output) → "Writes To"
 *   (File produces data for table, data flows FROM file TO table)
 * - From TABLE perspective: File is UPSTREAM (producer) → "Written To By"
 *   (File provides data to table, data flows FROM file TO table)
 * 
 * This module provides context-aware transformation of all relationship types.
 */

export interface RelationshipContext {
  relationship: string;
  viewingNodeType: string;
  direction: 'upstream' | 'downstream';
}

/**
 * All relationship types used in the lineage graph.
 * Based on EdgeRelationshipHelper in Python backend.
 */
export const RelationshipTypes = {
  // Primary relationships
  READS_FROM: 'READS_FROM',
  READS: 'READS',
  WRITES_TO: 'WRITES_TO',
  WRITES: 'WRITES',
  CREATES: 'CREATES',
  CREATES_INDEX: 'CREATES_INDEX',
  DELETES_FROM: 'DELETES_FROM',
  DROPS: 'DROPS',
  DEPENDS_ON: 'DEPENDS_ON',
  DEPENDS_ON_TABLE: 'DEPENDS_ON_TABLE',
} as const;

/**
 * Transform relationship label based on viewing context using DATA FLOW perspective.
 * 
 * Edge Direction: All edges flow FILE -> TABLE (file is source, table is target)
 * 
 * For TABLE_OR_VIEW nodes:
 * - UPSTREAM: Files that PRODUCE data (WRITES_TO, CREATES, etc.) - show passive voice
 *   (e.g., "Created By", "Written To By", "Dropped By")
 * - DOWNSTREAM: Files that CONSUME data (READS_FROM) - show passive voice
 *   (e.g., "Read By")
 * 
 * For FILE nodes:
 * - UPSTREAM: Tables the file DEPENDS ON (READS_FROM) - show active voice
 *   (e.g., "Reads From", "Depends On")
 * - DOWNSTREAM: Tables the file PRODUCES (CREATES, WRITES_TO, etc.) - show active voice
 *   (e.g., "Creates", "Writes To", "Drops")
 * 
 * @param context - The viewing context (relationship, node type, direction)
 * @returns User-friendly relationship label
 * 
 * @example
 * // Viewing a TABLE node (file reads from table: FILE --READS_FROM--> TABLE)
 * getContextualRelationshipLabel({
 *   relationship: 'READS_FROM',
 *   viewingNodeType: 'TABLE_OR_VIEW',
 *   direction: 'downstream'  // File is consumer (downstream from table)
 * }) // Returns: "Read By"
 * 
 * @example
 * // Viewing a FILE node (file reads from table: FILE --READS_FROM--> TABLE)
 * getContextualRelationshipLabel({
 *   relationship: 'READS_FROM',
 *   viewingNodeType: 'FILE',
 *   direction: 'upstream'  // Table is dependency (upstream from file)
 * }) // Returns: "Reads From"
 * 
 * @example
 * // Viewing a TABLE node (file writes to table: FILE --WRITES_TO--> TABLE)
 * getContextualRelationshipLabel({
 *   relationship: 'WRITES_TO',
 *   viewingNodeType: 'TABLE_OR_VIEW',
 *   direction: 'upstream'  // File is producer (upstream to table)
 * }) // Returns: "Written To By"
 * 
 * @example
 * // Viewing a FILE node (file creates table: FILE --CREATES--> TABLE)
 * getContextualRelationshipLabel({
 *   relationship: 'CREATES',
 *   viewingNodeType: 'FILE',
 *   direction: 'downstream'  // Table is output (downstream from file)
 * }) // Returns: "Creates"
 */
export function getContextualRelationshipLabel(context: RelationshipContext): string {
  const { relationship, viewingNodeType, direction } = context;
  
  const isTableView = viewingNodeType === 'TABLE_OR_VIEW' || viewingNodeType === 'TABLE' || viewingNodeType === 'VIEW';
  const isFileView = viewingNodeType === 'FILE';
  
  // Normalize relationship (handle both READS_FROM and READS variants)
  const normalizedRel = relationship.toUpperCase();
  
  // ============================================================================
  // TABLE_OR_VIEW NODE PERSPECTIVE
  // Data Flow Perspective: Consider what files DO with the table's data
  // ============================================================================
  if (isTableView) {
    // ------------------------------------------------------------------------
    // UPSTREAM relationships - Data PRODUCERS
    // Files that WRITE TO, CREATE, or modify the table (data flows FROM file TO table)
    // These files are upstream because they produce/provide data FOR the table
    // ------------------------------------------------------------------------
    if (direction === 'upstream') {
      // Creation operations - FILE creates TABLE (file is data producer)
      if (normalizedRel === 'CREATES') {
        return 'Created By';
      }
      
      // Index creation operations - FILE creates index on TABLE
      if (normalizedRel === 'CREATES_INDEX' || normalizedRel === 'CREATE_INDEX') {
        return 'Index Created By';
      }
      
      // Write operations - FILE writes to TABLE (INSERT/UPDATE)
      if (normalizedRel === 'WRITES_TO' || normalizedRel === 'WRITES') {
        return 'Written To By';
      }
      
      // Destructive data operations - FILE deletes from TABLE (DELETE/TRUNCATE)
      if (normalizedRel === 'DELETES_FROM') {
        return 'Deleted By';
      }
      
      // Metadata destruction - FILE drops TABLE (DROP TABLE)
      if (normalizedRel === 'DROPS') {
        return 'Dropped By';
      }
    }
    
    // ------------------------------------------------------------------------
    // DOWNSTREAM relationships - Data CONSUMERS
    // Files that READ FROM the table (data flows FROM table TO file)
    // These files are downstream because they consume data FROM the table
    // ------------------------------------------------------------------------
    if (direction === 'downstream') {
      // Read operations - FILE reads FROM table (file is data consumer)
      if (normalizedRel === 'READS_FROM' || normalizedRel === 'READS') {
        return 'Read By';
      }
      
      // Generic dependency
      if (normalizedRel === 'DEPENDS_ON' || normalizedRel === 'DEPENDS_ON_TABLE') {
        return 'Depended On By';
      }
    }
  }
  
  // ============================================================================
  // FILE NODE PERSPECTIVE
  // Data Flow Perspective: What the file does with data
  // ============================================================================
  if (isFileView) {
    // ------------------------------------------------------------------------
    // UPSTREAM relationships - Dependencies (tables the file READS FROM)
    // Data flows FROM table TO file (file consumes data)
    // ------------------------------------------------------------------------
    if (direction === 'upstream') {
      // Read operations - FILE reads FROM table (file depends on table's data)
      if (normalizedRel === 'READS_FROM' || normalizedRel === 'READS') {
        return 'Reads From';
      }
      
      // Generic dependencies
      if (normalizedRel === 'DEPENDS_ON') {
        return 'Depends On';
      }
      
      if (normalizedRel === 'DEPENDS_ON_TABLE') {
        return 'Depends On (via Table)';
      }
    }
    
    // ------------------------------------------------------------------------
    // DOWNSTREAM relationships - Outputs (tables the file WRITES TO/CREATES)
    // Data flows FROM file TO table (file produces data)
    // ------------------------------------------------------------------------
    if (direction === 'downstream') {
      // Creation operations - FILE creates TABLE (file is data producer)
      if (normalizedRel === 'CREATES') {
        return 'Creates';
      }
      
      // Index creation operations - FILE creates index on TABLE
      if (normalizedRel === 'CREATES_INDEX' || normalizedRel === 'CREATE_INDEX') {
        return 'Creates Index';
      }
      
      // Write operations - FILE writes TO table (INSERT/UPDATE)
      if (normalizedRel === 'WRITES_TO' || normalizedRel === 'WRITES') {
        return 'Writes To';
      }
      
      // Destructive data operations - FILE deletes FROM table (DELETE/TRUNCATE)
      if (normalizedRel === 'DELETES_FROM') {
        return 'Deletes From';
      }
      
      // Metadata destruction - FILE drops TABLE (DROP TABLE)
      if (normalizedRel === 'DROPS') {
        return 'Drops';
      }
    }
  }
  
  // ============================================================================
  // FALLBACK for unknown node types or relationships
  // ============================================================================
  return formatOperationName(relationship);
}

/**
 * Format a relationship/operation name for display.
 * Converts underscores to spaces and applies title case.
 * 
 * @param operation - The operation name (e.g., "READS_FROM", "WRITES_TO")
 * @returns Formatted operation name (e.g., "Reads From", "Writes To")
 * 
 * @example
 * formatOperationName('READS_FROM') // Returns: "Reads From"
 * formatOperationName('CREATE_INDEX') // Returns: "Create Index"
 */
export function formatOperationName(operation: string): string {
  return operation
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

/**
 * Get color scheme for relationship badge based on semantic meaning.
 * Consistent across all views for visual continuity.
 * 
 * Color meanings:
 * - Blue: Read operations (data consumption)
 * - Green: Write operations (data modification/creation)
 * - Purple: Table creation (metadata creation)
 * - Red: Destructive operations (delete/drop)
 * - Orange: Drop operations (metadata destruction)
 * - Gray: Generic dependencies
 * 
 * @param relationship - The relationship type
 * @returns Tailwind CSS classes for background and text color
 */
export function getRelationshipColor(relationship: string): string {
  const normalizedRel = relationship.toUpperCase();
  
  // Read operations - Blue
  if (normalizedRel.includes('READ')) {
    return 'bg-blue-100 text-blue-700';
  }
  
  // Creation operations - Purple
  if (normalizedRel === 'CREATES') {
    return 'bg-purple-100 text-purple-700';
  }
  
  // Index creation operations - Light Purple
  if (normalizedRel.includes('INDEX')) {
    return 'bg-purple-50 text-purple-600 border border-purple-200';
  }
  
  // Write operations (INSERT/UPDATE) - Green
  if (normalizedRel.includes('WRITE') || normalizedRel.includes('INSERT') || normalizedRel.includes('UPDATE')) {
    return 'bg-green-100 text-green-700';
  }
  
  // Destructive data operations (DELETE/TRUNCATE) - Red
  if (normalizedRel.includes('DELETE') || normalizedRel.includes('TRUNCATE')) {
    return 'bg-red-100 text-red-700';
  }
  
  // Metadata destruction (DROP) - Orange (different from DELETE for clarity)
  if (normalizedRel.includes('DROP')) {
    return 'bg-orange-100 text-orange-700';
  }
  
  // Generic dependencies - Gray
  if (normalizedRel.includes('DEPENDS')) {
    return 'bg-gray-100 text-gray-700';
  }
  
  // Fallback - Gray
  return 'bg-gray-100 text-gray-700';
}

/**
 * Get icon color for relationship visualization in graph view.
 * Matches the badge colors for consistency.
 */
export function getRelationshipIconColor(relationship: string): string {
  const normalizedRel = relationship.toUpperCase();
  
  if (normalizedRel.includes('READ')) return 'text-blue-500';
  if (normalizedRel === 'CREATES') return 'text-purple-500';
  if (normalizedRel.includes('INDEX')) return 'text-purple-400';
  if (normalizedRel.includes('WRITE')) return 'text-green-500';
  if (normalizedRel.includes('DELETE')) return 'text-red-500';
  if (normalizedRel.includes('DROP')) return 'text-orange-500';
  if (normalizedRel.includes('DEPENDS')) return 'text-gray-500';
  
  return 'text-gray-400';
}

/**
 * Get human-readable description of what a relationship means.
 * Useful for tooltips and help text.
 */
export function getRelationshipDescription(relationship: string): string {
  const normalizedRel = relationship.toUpperCase();
  
  switch (normalizedRel) {
    case 'READS_FROM':
    case 'READS':
      return 'Data is read from this table/view';
    case 'CREATES':
      return 'This table/view is created by the file';
    case 'CREATES_INDEX':
    case 'CREATE_INDEX':
      return 'An index is created on this table/view by the file';
    case 'WRITES_TO':
    case 'WRITES':
      return 'Data is written to this table/view (INSERT/UPDATE)';
    case 'DELETES_FROM':
      return 'Data is deleted from this table/view (DELETE/TRUNCATE)';
    case 'DROPS':
      return 'This table/view is dropped by the file';
    case 'DEPENDS_ON':
      return 'Generic dependency relationship';
    case 'DEPENDS_ON_TABLE':
      return 'Dependency via shared table usage';
    default:
      return relationship;
  }
}

