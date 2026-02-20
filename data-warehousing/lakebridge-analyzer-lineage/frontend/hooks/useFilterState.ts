/**
 * Custom hook for managing lineage filter state with localStorage persistence
 */

import { useState, useEffect, useCallback } from 'react';

export interface FilterState {
  searchQuery: string;
  nodeTypeFilter: string;
  selectedOperations: Set<string>;
  selectedFiles: string[];
  programPattern: string;
  objectPattern: string;
  showFileDependencies: boolean;
  viewMode: 'graph' | 'list';
  sortField: 'name' | 'type' | 'upstream' | 'downstream' | 'impact';
  sortDirection: 'asc' | 'desc';
}

const DEFAULT_FILTER_STATE: FilterState = {
  searchQuery: '',
  nodeTypeFilter: 'all',
  selectedOperations: new Set(),
  selectedFiles: [],
  programPattern: '',
  objectPattern: '',
  showFileDependencies: true,  // ON by default per plan
  viewMode: 'list',
  sortField: 'impact',
  sortDirection: 'desc',
};

const STORAGE_KEY = 'migration-accelerator:lineage-filters';

/**
 * Serialize filter state for localStorage
 */
function serializeFilterState(state: FilterState): string {
  return JSON.stringify({
    ...state,
    selectedOperations: Array.from(state.selectedOperations),
  });
}

/**
 * Deserialize filter state from localStorage
 */
function deserializeFilterState(json: string): FilterState {
  try {
    const parsed = JSON.parse(json);
    return {
      ...parsed,
      selectedOperations: new Set(parsed.selectedOperations || []),
    };
  } catch (error) {
    console.warn('Failed to parse filter state from localStorage:', error);
    return DEFAULT_FILTER_STATE;
  }
}

export function useFilterState() {
  const [filterState, setFilterState] = useState<FilterState>(() => {
    // Initialize from localStorage if available
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        return deserializeFilterState(stored);
      }
    }
    return DEFAULT_FILTER_STATE;
  });

  // Persist to localStorage on change
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, serializeFilterState(filterState));
    }
  }, [filterState]);

  // Individual setters for convenience
  const setSearchQuery = useCallback((searchQuery: string) => {
    setFilterState(prev => ({ ...prev, searchQuery }));
  }, []);

  const setNodeTypeFilter = useCallback((nodeTypeFilter: string) => {
    setFilterState(prev => ({ ...prev, nodeTypeFilter }));
  }, []);

  const setSelectedOperations = useCallback((selectedOperations: Set<string>) => {
    setFilterState(prev => ({ ...prev, selectedOperations }));
  }, []);

  const setSelectedFiles = useCallback((selectedFiles: string[]) => {
    setFilterState(prev => ({ ...prev, selectedFiles }));
  }, []);

  const setProgramPattern = useCallback((programPattern: string) => {
    setFilterState(prev => ({ ...prev, programPattern }));
  }, []);

  const setObjectPattern = useCallback((objectPattern: string) => {
    setFilterState(prev => ({ ...prev, objectPattern }));
  }, []);

  const setShowFileDependencies = useCallback((showFileDependencies: boolean) => {
    setFilterState(prev => ({ ...prev, showFileDependencies }));
  }, []);

  const setViewMode = useCallback((viewMode: 'graph' | 'list') => {
    setFilterState(prev => ({ ...prev, viewMode }));
  }, []);

  const setSortField = useCallback((sortField: FilterState['sortField']) => {
    setFilterState(prev => ({ ...prev, sortField }));
  }, []);

  const setSortDirection = useCallback((sortDirection: 'asc' | 'desc') => {
    setFilterState(prev => ({ ...prev, sortDirection }));
  }, []);

  // Reset all filters to defaults
  const resetFilters = useCallback(() => {
    setFilterState(DEFAULT_FILTER_STATE);
  }, []);

  // Check if any filters are active (non-default)
  const hasActiveFilters = useCallback(() => {
    return (
      filterState.searchQuery !== '' ||
      filterState.nodeTypeFilter !== 'all' ||
      filterState.selectedOperations.size > 0 ||
      filterState.selectedFiles.length > 0 ||
      filterState.programPattern !== '' ||
      filterState.objectPattern !== ''
    );
  }, [filterState]);

  // Count active filters
  const activeFilterCount = useCallback(() => {
    let count = 0;
    if (filterState.searchQuery) count++;
    if (filterState.nodeTypeFilter !== 'all') count++;
    if (filterState.selectedOperations.size > 0) count++;
    if (filterState.selectedFiles.length > 0) count++;
    if (filterState.programPattern) count++;
    if (filterState.objectPattern) count++;
    return count;
  }, [filterState]);

  return {
    // State
    filterState,
    
    // Setters
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
    
    // Bulk operations
    resetFilters,
    setFilterState,
    
    // Helpers
    hasActiveFilters: hasActiveFilters(),
    activeFilterCount: activeFilterCount(),
  };
}


