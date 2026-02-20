'use client';

import { useState } from 'react';
import { Search, X, Download, ChevronDown, Network, LayoutGrid, Filter as FilterIcon } from 'lucide-react';
import { Button } from '@/components';
import { getNodeTypeDisplayName } from '@/types/nodeTypes';
import { formatOperationName } from '@/types/relationshipLabels';

interface FilterToolbarProps {
  // Search
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onSearchSubmit: () => void;
  onSearchClear: () => void;
  
  // Type filter
  nodeTypeFilter: string;
  availableTypes: string[];
  nodeTypeCounts: Record<string, number>;
  onNodeTypeChange: (type: string) => void;
  
  // Operations filter
  selectedOperations: Set<string>;
  availableOperations: string[];
  onOperationsChange: (operations: Set<string>) => void;
  
  // Files filter
  selectedFiles: string[];
  availableFiles: Array<{ file_id: string; filename: string }>;
  onFilesChange: (fileIds: string[]) => void;
  onApplyFileFilter: () => void;
  
  // View mode
  viewMode: 'graph' | 'list';
  onViewModeChange: (mode: 'graph' | 'list') => void;
  
  // Export
  onExport: (format: 'json' | 'csv' | 'graphml') => void;
  exporting: boolean;
  
  // Clear all
  hasActiveFilters: boolean;
  onClearAll: () => void;
  
  // Advanced filters toggle
  showAdvancedFilters: boolean;
  onToggleAdvancedFilters: () => void;
  
  // Active filter count
  activeFilterCount: number;
}

export default function FilterToolbar({
  searchQuery,
  onSearchChange,
  onSearchSubmit,
  onSearchClear,
  nodeTypeFilter,
  availableTypes,
  nodeTypeCounts,
  onNodeTypeChange,
  selectedOperations,
  availableOperations,
  onOperationsChange,
  selectedFiles,
  availableFiles,
  onFilesChange,
  onApplyFileFilter,
  viewMode,
  onViewModeChange,
  onExport,
  exporting,
  hasActiveFilters,
  onClearAll,
  showAdvancedFilters,
  onToggleAdvancedFilters,
  activeFilterCount,
}: FilterToolbarProps) {
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showTypeDropdown, setShowTypeDropdown] = useState(false);
  const [showOperationsDropdown, setShowOperationsDropdown] = useState(false);
  const [showFilesDropdown, setShowFilesDropdown] = useState(false);

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
      {/* Primary Toolbar Row */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search Bar */}
        <div className="flex-1 min-w-[300px] relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && onSearchSubmit()}
            placeholder="Search tables, views, files... (Press Enter)"
            className="w-full pl-10 pr-10 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-gray-900 text-sm"
          />
          {searchQuery && (
            <button
              onClick={onSearchClear}
              className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title="Clear search"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Type Filter Dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowTypeDropdown(!showTypeDropdown)}
            className={`border rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-2 ${
              nodeTypeFilter !== 'all'
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
            }`}
            title="Filter by node type"
          >
            Types
            {nodeTypeFilter !== 'all' && (
              <span className="bg-blue-600 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                1
              </span>
            )}
            <ChevronDown className="w-4 h-4" />
          </button>
          
          {showTypeDropdown && (
            <div className="absolute top-full left-0 mt-1 w-60 bg-white rounded-lg shadow-lg border border-gray-200 p-3 z-20 max-h-80 overflow-y-auto">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-semibold text-gray-900">Select Type</span>
                {nodeTypeFilter !== 'all' && (
                  <button
                    onClick={() => {
                      onNodeTypeChange('all');
                      setShowTypeDropdown(false);
                    }}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    Clear
                  </button>
                )}
              </div>
              
              <div className="space-y-1">
                <button
                  onClick={() => {
                    onNodeTypeChange('all');
                    setShowTypeDropdown(false);
                  }}
                  className={`w-full text-left px-3 py-2 rounded text-sm flex items-center justify-between ${
                    nodeTypeFilter === 'all' 
                      ? 'bg-blue-50 text-blue-700 font-medium' 
                      : 'text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  <span>All Types</span>
                  <span className="text-xs text-gray-500">
                    {Object.values(nodeTypeCounts).reduce((a, b) => a + b, 0)}
                  </span>
                </button>
                
                {availableTypes.map(type => (
                  <button
                    key={type}
                    onClick={() => {
                      onNodeTypeChange(type);
                      setShowTypeDropdown(false);
                    }}
                    className={`w-full text-left px-3 py-2 rounded text-sm flex items-center justify-between ${
                      nodeTypeFilter === type 
                        ? 'bg-blue-50 text-blue-700 font-medium' 
                        : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <span>{getNodeTypeDisplayName(type)}</span>
                    <span className="text-xs text-gray-500">{nodeTypeCounts[type] || 0}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Operations Filter */}
        <div className="relative">
          <button
            onClick={() => setShowOperationsDropdown(!showOperationsDropdown)}
            className={`border rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-2 ${
              selectedOperations.size > 0
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
            }`}
            title="Filter by operations"
          >
            Operations
            {selectedOperations.size > 0 && (
              <span className="bg-blue-600 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                {selectedOperations.size}
              </span>
            )}
            <ChevronDown className="w-4 h-4" />
          </button>
          
          {showOperationsDropdown && (
            <div className="absolute top-full left-0 mt-1 w-64 bg-white rounded-lg shadow-lg border border-gray-200 p-3 z-20">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-gray-900">Select Operations</span>
                {selectedOperations.size > 0 && (
                  <button
                    onClick={() => onOperationsChange(new Set())}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    Clear
                  </button>
                )}
              </div>
              <div className="space-y-1 max-h-80 overflow-y-auto border border-gray-200 rounded p-2 bg-gray-50">
                {availableOperations.map(op => (
                  <label key={op} className="flex items-center space-x-2 cursor-pointer hover:bg-gray-100 p-1.5 rounded">
                    <input
                      type="checkbox"
                      checked={selectedOperations.has(op)}
                      onChange={(e) => {
                        const newOps = new Set(selectedOperations);
                        if (e.target.checked) {
                          newOps.add(op);
                        } else {
                          newOps.delete(op);
                        }
                        onOperationsChange(newOps);
                      }}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 flex-shrink-0"
                    />
                    <span className="text-sm text-gray-700">{formatOperationName(op)}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Files Filter */}
        <div className="relative">
          <button
            onClick={() => setShowFilesDropdown(!showFilesDropdown)}
            className={`border rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-2 ${
              selectedFiles.length > 0
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
            }`}
            title="Filter by source files"
          >
            Files
            {selectedFiles.length > 0 && (
              <span className="bg-blue-600 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                {selectedFiles.length}
              </span>
            )}
            <ChevronDown className="w-4 h-4" />
          </button>
          
          {showFilesDropdown && (
            <div className="absolute top-full left-0 mt-1 w-80 bg-white rounded-lg shadow-lg border border-gray-200 p-3 z-20">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-gray-900">Select Files</span>
                <div className="flex gap-2">
                  {selectedFiles.length > 0 && (
                    <button
                      onClick={() => onFilesChange([])}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
              <div className="space-y-1 max-h-60 overflow-y-auto border border-gray-200 rounded p-2 bg-gray-50">
                {availableFiles.map(file => (
                  <label key={file.file_id} className="flex items-center space-x-2 cursor-pointer hover:bg-gray-100 p-1 rounded">
                    <input
                      type="checkbox"
                      checked={selectedFiles.includes(file.file_id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          onFilesChange([...selectedFiles, file.file_id]);
                        } else {
                          onFilesChange(selectedFiles.filter(id => id !== file.file_id));
                        }
                      }}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 flex-shrink-0"
                    />
                    <span className="text-xs text-gray-700 break-words" title={file.filename}>
                      {file.filename}
                    </span>
                  </label>
                ))}
              </div>
              {selectedFiles.length > 0 && (
                <button
                  onClick={() => {
                    onApplyFileFilter();
                    setShowFilesDropdown(false);
                  }}
                  className="mt-2 w-full px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700"
                >
                  Apply Filter
                </button>
              )}
            </div>
          )}
        </div>

        {/* View Mode Toggle */}
        <button
          onClick={() => onViewModeChange(viewMode === 'graph' ? 'list' : 'graph')}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-2 bg-white text-gray-700 hover:bg-gray-50"
          title={viewMode === 'list' ? 'Switch to Graph View' : 'Switch to List View'}
        >
          {viewMode === 'list' ? (
            <>
              <Network className="w-4 h-4" />
              Graph
            </>
          ) : (
            <>
              <LayoutGrid className="w-4 h-4" />
              List
            </>
          )}
        </button>

        {/* Export Menu */}
        <div className="relative">
          <button
            onClick={() => setShowExportMenu(!showExportMenu)}
            disabled={exporting}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-2 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            title="Export lineage data"
          >
            {exporting ? (
              <>
                <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                Export
                <ChevronDown className="w-4 h-4" />
              </>
            )}
          </button>
          
          {showExportMenu && !exporting && (
            <div className="absolute top-full right-0 mt-1 w-48 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-20">
              <button
                onClick={() => {
                  onExport('json');
                  setShowExportMenu(false);
                }}
                className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 flex items-center"
              >
                <Download className="w-4 h-4 mr-2" />
                JSON Format
              </button>
              <button
                onClick={() => {
                  onExport('csv');
                  setShowExportMenu(false);
                }}
                className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 flex items-center"
              >
                <Download className="w-4 h-4 mr-2" />
                CSV Edge List
              </button>
              <button
                onClick={() => {
                  onExport('graphml');
                  setShowExportMenu(false);
                }}
                className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 flex items-center"
              >
                <Download className="w-4 h-4 mr-2" />
                GraphML Format
              </button>
            </div>
          )}
        </div>

        {/* Advanced Filters Toggle */}
        <button
          onClick={onToggleAdvancedFilters}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-2 bg-white text-gray-700 hover:bg-gray-50"
          title="Show/hide advanced filters"
        >
          <FilterIcon className="w-4 h-4" />
          {showAdvancedFilters ? 'Hide' : 'More'}
        </button>

        {/* Clear All Button */}
        {hasActiveFilters && (
          <button
            onClick={onClearAll}
            className="border border-red-300 rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-2 bg-red-50 text-red-700 hover:bg-red-100"
            title="Clear all filters and reset"
          >
            <X className="w-4 h-4" />
            Clear All
            {activeFilterCount > 0 && (
              <span className="bg-red-600 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                {activeFilterCount}
              </span>
            )}
          </button>
        )}
      </div>

      {/* Active Filters Summary */}
      {hasActiveFilters && (
        <div className="text-xs text-gray-600 flex items-center gap-2 flex-wrap">
          <span className="font-semibold">Active filters:</span>
          {searchQuery && <span className="bg-blue-100 text-blue-800 px-2 py-1 rounded">Search: "{searchQuery}"</span>}
          {nodeTypeFilter !== 'all' && <span className="bg-blue-100 text-blue-800 px-2 py-1 rounded">Type: {getNodeTypeDisplayName(nodeTypeFilter)}</span>}
          {selectedOperations.size > 0 && <span className="bg-blue-100 text-blue-800 px-2 py-1 rounded">{selectedOperations.size} operation{selectedOperations.size > 1 ? 's' : ''}</span>}
          {selectedFiles.length > 0 && <span className="bg-blue-100 text-blue-800 px-2 py-1 rounded">{selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''}</span>}
        </div>
      )}
    </div>
  );
}

