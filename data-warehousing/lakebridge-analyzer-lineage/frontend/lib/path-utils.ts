/**
 * Utility functions for handling and displaying file paths
 */

/**
 * Truncate a file path to show only the filename and its parent folder
 * This prevents UI overflow while maintaining useful context
 * 
 * @param fullPath - The complete file path
 * @returns Truncated path in the format "parentFolder/filename.ext"
 * 
 * @example
 * truncateFilePath("folder1/folder2/folder3/file.sql") // Returns: "folder3/file.sql"
 * truncateFilePath("file.sql") // Returns: "file.sql"
 * truncateFilePath("folder/file.sql") // Returns: "folder/file.sql"
 */
export function truncateFilePath(fullPath: string): string {
  if (!fullPath) return '';
  
  // Handle both forward slashes and backslashes
  const normalizedPath = fullPath.replace(/\\/g, '/');
  const parts = normalizedPath.split('/');
  
  // If path has 2 or fewer parts, return as-is
  if (parts.length <= 2) {
    return normalizedPath;
  }
  
  // Return last 2 parts (parent folder + filename)
  return parts.slice(-2).join('/');
}

/**
 * Get the filename from a full path
 * 
 * @param fullPath - The complete file path
 * @returns Just the filename with extension
 * 
 * @example
 * getFileName("folder1/folder2/file.sql") // Returns: "file.sql"
 */
export function getFileName(fullPath: string): string {
  if (!fullPath) return '';
  
  const normalizedPath = fullPath.replace(/\\/g, '/');
  const parts = normalizedPath.split('/');
  
  return parts[parts.length - 1] || '';
}

/**
 * Get the parent folder name from a full path
 * 
 * @param fullPath - The complete file path
 * @returns The immediate parent folder name, or empty string if none
 * 
 * @example
 * getParentFolder("folder1/folder2/file.sql") // Returns: "folder2"
 */
export function getParentFolder(fullPath: string): string {
  if (!fullPath) return '';
  
  const normalizedPath = fullPath.replace(/\\/g, '/');
  const parts = normalizedPath.split('/');
  
  if (parts.length <= 1) return '';
  
  return parts[parts.length - 2] || '';
}



