/**
 * Node type constants and utilities with UI normalization.
 * 
 * Backend uses technical constants (FILE, TABLE_OR_VIEW).
 * Frontend displays user-friendly names ("File", "Table or View").
 */

export const NodeTypes = {
  FILE: 'FILE',
  TABLE_OR_VIEW: 'TABLE_OR_VIEW',
} as const;

export type NodeType = typeof NodeTypes[keyof typeof NodeTypes];

// UI display names (no uppercase, no underscores)
export const NodeTypeDisplayNames: Record<NodeType, string> = {
  [NodeTypes.FILE]: 'File',
  [NodeTypes.TABLE_OR_VIEW]: 'Table or View',
};

/**
 * Get user-friendly display name for a node type.
 * 
 * @example
 * getNodeTypeDisplayName('FILE') // "File"
 * getNodeTypeDisplayName('TABLE_OR_VIEW') // "Table or View"
 */
export const getNodeTypeDisplayName = (type: string): string => {
  return NodeTypeDisplayNames[type as NodeType] || type;
};

export const isTableNode = (type: string): boolean => {
  return type === NodeTypes.TABLE_OR_VIEW;
};

export const isFileNode = (type: string): boolean => {
  return type === NodeTypes.FILE;
};

/**
 * Legacy type normalization (if needed for old data).
 * GLOBAL_TEMP_TABLE → TABLE_OR_VIEW
 */
export const normalizeNodeType = (type: string): NodeType => {
  if (type === 'GLOBAL_TEMP_TABLE') {
    return NodeTypes.TABLE_OR_VIEW;
  }
  return type as NodeType;
};
