/**
 * Utility functions
 */

import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind CSS classes
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format file size
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes';

  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

/**
 * Format date
 */
export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

/**
 * Capitalize first letter
 */
export function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Get color for node type
 */
export function getNodeColor(nodeType: string): string {
  const colors: Record<string, string> = {
    Script: '#FF6B6B',
    Table: '#4ECDC4',
    File: '#45B7D1',
    View: '#96CEB4',
    Database: '#FFEAA7',
    Column: '#DDA0DD',
  };
  return colors[nodeType] || '#97C2FC';
}

/**
 * Get color for relationship
 */
export function getRelationshipColor(relationship: string): string {
  const colors: Record<string, string> = {
    READS_FROM: '#85C1E9',
    WRITES_TO: '#F1948A',
    TRANSFORMS: '#82E0AA',
    DEPENDS_ON: '#D7DBDD',
  };
  return colors[relationship] || '#848484';
}

/**
 * Calculate complexity level
 */
export function getComplexityLevel(complexity: Record<string, number>): string {
  const total = Object.values(complexity).reduce((sum, val) => sum + val, 0);
  const veryComplex = complexity['VERY_COMPLEX'] || 0;
  const complex = complexity['COMPLEX'] || 0;

  if (total === 0) return 'Unknown';
  
  const ratio = (veryComplex + complex) / total;
  
  if (ratio > 0.3) return 'High';
  if (ratio > 0.1) return 'Medium';
  return 'Low';
}

/**
 * Parse error message
 */
export function getErrorMessage(error: any): string {
  if (error.response?.data?.error) {
    return error.response.data.error;
  }
  if (error.message) {
    return error.message;
  }
  return 'An unexpected error occurred';
}




