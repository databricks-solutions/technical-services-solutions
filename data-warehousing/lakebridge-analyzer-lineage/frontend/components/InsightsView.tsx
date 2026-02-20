'use client';

import { useState, useEffect, memo } from 'react';
import { TrendingUp, Database, GitBranch, AlertCircle, Download, ArrowRight, Package, Upload } from 'lucide-react';
import api from '@/lib/api';
import type { LineageInsightsResponse } from '@/lib/api';
import { Card, ErrorMessage, Button } from '@/components';
import { getErrorMessage } from '@/lib/utils';
import { truncateFilePath } from '@/lib/path-utils';
import { getNodeTypeDisplayName } from '@/types/nodeTypes';
import { useToast } from '@/hooks/useToast';

interface MigrationNode {
  node_id: string;
  name: string;
  type: string;
  upstream_count: number;
  downstream_count: number;
  upstream_files?: string[];
  downstream_files?: string[];
  pre_existing_tables?: string[];
  pre_existing_table_count?: number;
  rationale: string;
  source_files: Array<{ file_id: string; filename: string }>;
}

interface MigrationWave {
  wave_number: number;
  nodes: MigrationNode[];
}

interface MigrationGroup {
  group_number: number;
  group_name: string;
  files_count: number;
  tables_count: number;
  waves: MigrationWave[];
  tables_involved: string[];
}

interface PreExistingTable {
  table_id: string;
  table_name: string;
  type: string;
  referenced_by_files: string[];
  referencing_file_names: string[];
  read_by_count: number;
  written_by_count: number;
  total_references: number;
}

interface MigrationOrderData {
  groups: MigrationGroup[];
  total_nodes: number;
  total_groups: number;
  has_cycles: boolean;
  cycle_info?: string;
  pre_existing_tables?: PreExistingTable[];
  table_dependencies?: any;
}

interface InsightsViewProps {
  onViewFileLineage?: (nodeId: string) => void;
  hasFiles?: boolean;
  onNavigateToFiles?: () => void;
}

function InsightsView({ onViewFileLineage, hasFiles = true, onNavigateToFiles }: InsightsViewProps) {
  const [insights, setInsights] = useState<LineageInsightsResponse | null>(null);
  const [migrationOrder, setMigrationOrder] = useState<MigrationOrderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<number | null>(null);
  const [selectedWave, setSelectedWave] = useState<string | null>(null); // "groupNum-waveNum"
  const { showToast } = useToast();

  useEffect(() => {
    // Only load insights if there are files
    if (hasFiles) {
      loadAllInsights();
    } else {
      setLoading(false);
    }
  }, [hasFiles]);

  const loadAllInsights = async () => {
    try {
      setLoading(true);
      setError(null);

      // Load insights and migration order in parallel
      const [insightsData, migrationData] = await Promise.all([
        api.getAggregateLineageInsights().catch(() => null),
        api.getMigrationOrder().catch(() => null)
      ]);

      setInsights(insightsData);
      setMigrationOrder(migrationData as MigrationOrderData | null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleExportInsights = async () => {
    try {
      const data = {
        insights,
        migration_order: migrationOrder,
        generated_at: new Date().toISOString()
      };

      const dataStr = JSON.stringify(data, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `migration-insights-${new Date().toISOString().split('T')[0]}.json`;
      link.click();
      URL.revokeObjectURL(url);
      showToast('Insights exported successfully', 'success');
    } catch (err) {
      showToast('Export failed: ' + getErrorMessage(err), 'error');
    }
  };

  // Empty state for first-time users
  if (!hasFiles && !loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Card className="max-w-2xl w-full text-center p-12">
          <div className="flex justify-center mb-6">
            <div className="w-24 h-24 rounded-full bg-gradient-to-br from-blue-100 to-purple-100 flex items-center justify-center">
              <Upload className="w-12 h-12 text-blue-600" />
            </div>
          </div>
          
          <h2 className="text-3xl font-bold text-gray-900 mb-4">
            Welcome to Migration Accelerator!
          </h2>
          
          <p className="text-lg text-gray-600 mb-8 max-w-lg mx-auto">
            Upload your first analyzer file to discover insights, visualize data lineage, 
            and plan your migration with confidence.
          </p>

          <Button
            onClick={onNavigateToFiles}
            size="lg"
            className="mx-auto mb-8"
          >
            <Upload className="w-5 h-5 mr-2" />
            Upload Your First File
          </Button>

          <div className="pt-8 border-t border-gray-200">
            <p className="text-sm font-semibold text-gray-700 mb-4">Supported Platforms:</p>
            <div className="flex flex-wrap justify-center gap-4 text-sm text-gray-600">
              {/* <span className="px-4 py-2 bg-gray-100 rounded-full">Talend</span> */}
              {/* <span className="px-4 py-2 bg-gray-100 rounded-full">Informatica</span> */}
              <span className="px-4 py-2 bg-gray-100 rounded-full">SQL-based Data Warehouses</span>
              {/* <span className="px-4 py-2 bg-gray-100 rounded-full">DataStage</span> */}
            </div>
          </div>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        {/* Header Skeleton */}
        <div className="flex items-center justify-between">
          <div className="flex-1">
            <div className="h-8 bg-gray-200 rounded w-80 mb-2" />
            <div className="h-4 bg-gray-200 rounded w-96" />
          </div>
          <div className="h-10 w-36 bg-gray-200 rounded" />
        </div>

        {/* Migration Order Card Skeleton */}
        <Card className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex-1">
              <div className="flex items-center mb-2">
                <div className="w-6 h-6 bg-gray-200 rounded mr-2" />
                <div className="h-6 bg-gray-200 rounded w-64" />
              </div>
              <div className="h-4 bg-gray-200 rounded w-80" />
            </div>
          </div>

          {/* Pre-existing Tables Warning Skeleton */}
          <div className="mb-6 bg-orange-50 border-2 border-orange-200 rounded-lg overflow-hidden">
            <div className="px-6 py-4 bg-orange-100 border-b border-orange-200">
              <div className="flex items-center">
                <div className="w-6 h-6 bg-orange-200 rounded mr-3" />
                <div className="flex-1">
                  <div className="h-5 bg-orange-200 rounded w-64 mb-2" />
                  <div className="h-3 bg-orange-200 rounded w-full" />
                </div>
              </div>
            </div>
            <div className="p-6 space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="border-2 border-orange-200 rounded-lg p-4 bg-white">
                  <div className="h-5 bg-gray-200 rounded w-48 mb-2" />
                  <div className="flex items-center space-x-3 mb-2">
                    <div className="h-5 w-20 bg-gray-200 rounded" />
                    <div className="h-4 w-16 bg-gray-200 rounded" />
                    <div className="h-4 w-16 bg-gray-200 rounded" />
                  </div>
                  <div className="space-y-1">
                    <div className="h-3 bg-gray-200 rounded w-40 mb-1" />
                    <div className="flex flex-wrap gap-1">
                      {[1, 2, 3, 4].map((j) => (
                        <div key={j} className="h-5 w-24 bg-gray-200 rounded" />
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Migration Groups Skeleton */}
          <div className="space-y-6">
            {[1, 2, 3].map((group) => (
              <div key={group} className="border-2 border-gray-300 rounded-lg overflow-hidden shadow-sm">
                <div className="px-6 py-5 bg-gradient-to-r from-blue-50 to-blue-100 flex items-center justify-between">
                  <div className="flex items-center space-x-4">
                    <div className="w-14 h-14 rounded-full bg-gray-200" />
                    <div>
                      <div className="h-6 bg-gray-200 rounded w-48 mb-2" />
                      <div className="h-4 bg-gray-200 rounded w-32" />
                    </div>
                  </div>
                  <div className="w-6 h-6 bg-gray-200 rounded" />
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Additional Insights Cards Skeleton */}
        <div className="grid md:grid-cols-2 gap-6">
          {/* Most Connected Nodes Skeleton */}
          <Card className="p-6">
            <div className="flex items-center mb-4">
              <div className="w-5 h-5 bg-gray-200 rounded mr-2" />
              <div className="h-5 bg-gray-200 rounded w-48" />
            </div>
            <div className="space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="h-4 bg-gray-200 rounded w-40 mb-2" />
                  <div className="flex items-center space-x-2">
                    <div className="h-3 w-16 bg-gray-200 rounded" />
                    <div className="h-3 w-24 bg-gray-200 rounded" />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Tables Never Read Skeleton */}
          <Card className="p-6">
            <div className="flex items-center mb-4">
              <div className="w-5 h-5 bg-gray-200 rounded mr-2" />
              <div className="h-5 bg-gray-200 rounded w-48" />
            </div>
            <div className="space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="h-4 bg-gray-200 rounded w-40 mb-2" />
                  <div className="flex items-center space-x-2">
                    <div className="h-3 w-16 bg-gray-200 rounded" />
                    <div className="h-3 w-20 bg-gray-200 rounded" />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Tables Only Read Skeleton */}
          <Card className="p-6">
            <div className="flex items-center mb-4">
              <div className="w-5 h-5 bg-gray-200 rounded mr-2" />
              <div className="h-5 bg-gray-200 rounded w-48" />
            </div>
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="h-4 bg-gray-200 rounded w-40 mb-2" />
                  <div className="h-3 w-32 bg-gray-200 rounded" />
                </div>
              ))}
            </div>
          </Card>

          {/* External Tables Skeleton */}
          <Card className="p-6">
            <div className="flex items-center mb-4">
              <div className="w-5 h-5 bg-gray-200 rounded mr-2" />
              <div className="h-5 bg-gray-200 rounded w-48" />
            </div>
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="h-4 bg-gray-200 rounded w-40 mb-2" />
                  <div className="h-3 w-32 bg-gray-200 rounded" />
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <Card>
        <ErrorMessage message={error} />
        <Button onClick={loadAllInsights} className="mt-4">
          Retry
        </Button>
      </Card>
    );
  }

  if (!insights) {
    return (
      <Card className="p-12 text-center">
        <Database className="w-16 h-16 mx-auto mb-4 text-gray-300" />
        <h3 className="text-xl font-bold text-gray-900 mb-2">No Data Available</h3>
        <p className="text-gray-600">
          Upload some analyzer files to see insights and migration recommendations
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Export */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Migration Insights & Analytics</h2>
          <p className="text-gray-600 mt-1">Comprehensive analysis and recommended migration order</p>
        </div>
        <Button onClick={handleExportInsights} variant="secondary">
          <Download className="w-4 h-4 mr-2" />
          Export Report
        </Button>
      </div>

      {/* Migration Order Recommendation */}
      {migrationOrder && (
        <Card>
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-xl font-bold text-gray-900 flex items-center">
                <TrendingUp className="w-6 h-6 mr-2 text-blue-600" />
                Recommended Migration Order
              </h3>
              <p className="text-sm text-gray-600 mt-1">
                {migrationOrder.total_nodes} files organized into {migrationOrder.total_groups} migration groups based on shared dependencies
              </p>
            </div>
          </div>

          {migrationOrder.has_cycles && (
            <div className="mb-4 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
              <div className="flex items-start">
                <AlertCircle className="w-5 h-5 text-yellow-600 mr-2 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-yellow-900">Circular Dependencies Detected</p>
                  <p className="text-sm text-yellow-700 mt-1">{migrationOrder.cycle_info}</p>
                </div>
              </div>
            </div>
          )}

          {/* Pre-existing Tables Warning */}
          {migrationOrder.pre_existing_tables && migrationOrder.pre_existing_tables.length > 0 && (
            <div className="mb-6 bg-orange-50 border-2 border-orange-200 rounded-lg overflow-hidden">
              <div className="px-6 py-4 bg-orange-100 border-b border-orange-200">
                <div className="flex items-center">
                  <AlertCircle className="w-6 h-6 text-orange-600 mr-3" />
                  <div>
                    <h4 className="font-bold text-orange-900">
                      Pre-existing Tables Required ({migrationOrder.pre_existing_tables.length})
                    </h4>
                    <p className="text-sm text-orange-800 mt-1">
                      These tables are referenced but never explicity created. Ensure they exist in Databricks before code validation.
                    </p>
                  </div>
                </div>
              </div>
              <div className="p-6 max-h-96 overflow-y-auto">
                <div className="space-y-3">
                  {migrationOrder.pre_existing_tables.map((table) => (
                    <div key={table.table_id} className="border-2 border-orange-200 rounded-lg p-4 bg-white hover:bg-orange-50 hover:border-orange-300 transition-all">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <button
                            onClick={() => {
                              if (onViewFileLineage) {
                                onViewFileLineage(table.table_id);
                              }
                            }}
                            className="font-semibold text-blue-600 hover:text-blue-800 hover:underline mb-1 text-left inline-flex items-center group"
                            title={`${table.table_name} - Click to view in lineage graph`}
                          >
                            {table.table_name}
                            <span className="ml-1 opacity-0 group-hover:opacity-100 transition-opacity text-xs">→</span>
                          </button>
                          <div className="flex items-center space-x-3 text-xs text-gray-600 mb-2">
                            <span className="px-2 py-0.5 bg-orange-100 text-orange-800 rounded font-medium">
                              {getNodeTypeDisplayName(table.type)}
                            </span>
                            <span>{table.read_by_count} reads</span>
                            <span>{table.written_by_count} writes</span>
                          </div>
                          <div className="mt-2">
                            <p className="text-xs text-gray-600 font-medium mb-1">
                              Referenced by {table.total_references} file(s):
                            </p>
                            <div className="flex flex-wrap gap-1">
                              {table.referencing_file_names.slice(0, 5).map((filename, idx) => (
                                <span key={idx} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded" title={filename}>
                                  {truncateFilePath(filename)}
                                </span>
                              ))}
                              {table.referencing_file_names.length > 5 && (
                                <span className="text-xs text-gray-500 italic">
                                  +{table.referencing_file_names.length - 5} more
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="space-y-6">
            {migrationOrder.groups.map((group) => (
              <div key={group.group_number} className="border-2 border-gray-300 rounded-lg overflow-hidden shadow-sm">
                {/* Group Header */}
                <button
                  onClick={() => setSelectedGroup(selectedGroup === group.group_number ? null : group.group_number)}
                  className="w-full px-6 py-5 bg-gradient-to-r from-blue-50 to-blue-100 hover:from-blue-100 hover:to-blue-200 transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center space-x-4">
                    <div className="w-14 h-14 rounded-full bg-blue-600 flex items-center justify-center shadow-md">
                      <Package className="w-7 h-7 text-white" />
                    </div>
                    <div className="text-left">
                      <h4 className="font-bold text-gray-900 text-lg">Group {group.group_number}: {group.group_name}</h4>
                      <p className="text-sm text-gray-700 mt-1">
                        {group.tables_count} table{group.tables_count !== 1 ? 's' : ''}, {group.files_count} file{group.files_count !== 1 ? 's' : ''}
                      </p>
                    </div>
                  </div>
                  <ArrowRight className={`w-6 h-6 text-gray-600 transition-transform ${
                    selectedGroup === group.group_number ? 'rotate-90' : ''
                  }`} />
                </button>

                {/* Group Content - Waves */}
                {selectedGroup === group.group_number && (
                  <div className="bg-white p-6">
                    {/* Tables Involved */}
                    {group.tables_involved && group.tables_involved.length > 0 && (
                      <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                        <p className="text-sm font-semibold text-blue-900 mb-2">
                          Tables in this group ({group.tables_involved.length}):
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {group.tables_involved.slice(0, 10).map((table, idx) => (
                            <span key={idx} className="text-xs bg-white text-blue-700 px-2 py-1 rounded border border-blue-200" title={table}>
                              {table}
                            </span>
                          ))}
                          {group.tables_involved.length > 10 && (
                            <span className="text-xs text-blue-600 italic px-2 py-1">
                              +{group.tables_involved.length - 10} more...
                            </span>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Waves within Group */}
                    <div className="space-y-4">
                      {group.waves.map((wave) => (
                        <div key={`${group.group_number}-${wave.wave_number}`} className="border border-gray-200 rounded-lg overflow-hidden">
                          <button
                            onClick={() => {
                              const waveKey = `${group.group_number}-${wave.wave_number}`;
                              setSelectedWave(selectedWave === waveKey ? null : waveKey);
                            }}
                            className="w-full px-5 py-4 bg-gray-50 hover:bg-gray-100 transition-colors flex items-center justify-between"
                          >
                            <div className="flex items-center space-x-3">
                              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
                                <span className="text-base font-bold text-blue-700">{wave.wave_number}</span>
                              </div>
                              <div className="text-left">
                                <h5 className="font-semibold text-gray-900">Wave {wave.wave_number}</h5>
                                <p className="text-sm text-gray-600">{wave.nodes.length} file{wave.nodes.length !== 1 ? 's' : ''}</p>
                              </div>
                            </div>
                            <ArrowRight className={`w-4 h-4 text-gray-400 transition-transform ${
                              selectedWave === `${group.group_number}-${wave.wave_number}` ? 'rotate-90' : ''
                            }`} />
                          </button>

                          {selectedWave === `${group.group_number}-${wave.wave_number}` && (
                            <div className="p-5 bg-white">
                              <div className="space-y-3">
                                {wave.nodes.map((node) => (
                        <div key={node.node_id} className="border-2 border-gray-200 rounded-lg p-4 hover:bg-blue-50 hover:border-blue-300 transition-all">
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <div className="flex items-center space-x-2 mb-2">
                                <button
                                  onClick={() => {
                                    if (onViewFileLineage) {
                                      onViewFileLineage(node.node_id);
                                    }
                                  }}
                                  className="font-semibold text-blue-600 hover:text-blue-800 hover:underline text-left inline-flex items-center group"
                                  title={`${node.name} - Click to view lineage`}
                                >
                                  {truncateFilePath(node.name)}
                                  <span className="ml-1 opacity-0 group-hover:opacity-100 transition-opacity text-xs">→</span>
                                </button>
                                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-700">
                                  {getNodeTypeDisplayName(node.type)}
                                </span>
                              </div>
                              
                              {/* Dependencies */}
                              {node.upstream_count === 0 && (!node.pre_existing_tables || node.pre_existing_tables.length === 0) ? (
                                <p className="text-sm text-gray-600 mb-2">No dependencies - can be migrated first</p>
                              ) : (
                                <div className="mb-2 space-y-2">
                                  {node.upstream_files && node.upstream_files.length > 0 && (
                                    <div>
                                      <p className="text-sm text-gray-700 font-medium mb-1">Depends on files:</p>
                                      <ul className="list-disc list-inside space-y-0.5 text-sm text-gray-600 pl-2">
                                        {node.upstream_files.map((file, idx) => (
                                          <li key={idx} title={file}>
                                            {truncateFilePath(file)}
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}
                                  
                                  {node.pre_existing_tables && node.pre_existing_tables.length > 0 && (
                                    <div className="bg-orange-50 border-l-2 border-orange-400 pl-3 py-1">
                                      <p className="text-sm text-orange-900 font-medium mb-1">
                                        ⚠️ Requires {node.pre_existing_tables.length} pre-existing table(s):
                                      </p>
                                      <ul className="list-disc list-inside space-y-0.5 text-xs text-orange-800 pl-2">
                                        {node.pre_existing_tables.slice(0, 3).map((table, idx) => (
                                          <li key={idx} title={table}>
                                            {table}
                                          </li>
                                        ))}
                                        {node.pre_existing_tables.length > 3 && (
                                          <li className="text-orange-600">
                                            +{node.pre_existing_tables.length - 3} more...
                                          </li>
                                        )}
                                      </ul>
                                    </div>
                                  )}
                                </div>
                              )}
                              
                              <div className="flex items-center space-x-4 text-xs">
                                <span className="text-gray-500">
                                  ↑ {node.upstream_count} file{node.upstream_count !== 1 ? 's' : ''}
                                  {node.pre_existing_table_count && node.pre_existing_table_count > 0 && (
                                    <span className="text-orange-600 font-medium">
                                      , ⚠️ {node.pre_existing_table_count} pre-existing table{node.pre_existing_table_count !== 1 ? 's' : ''}
                                    </span>
                                  )}
                                </span>
                                <span className="text-gray-500">↓ {node.downstream_count} dependent{node.downstream_count !== 1 ? 's' : ''}</span>
                              </div>
                              {node.source_files.length > 0 && (
                                <div className="mt-2">
                                  <p className="text-xs text-gray-500">Created in:</p>
                                  <div className="flex flex-wrap gap-1 mt-1">
                                    {node.source_files.map((file) => (
                                      <span key={file.file_id} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded break-words" title={file.filename}>
                                        {truncateFilePath(file.filename)}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

      {/* Most Connected Nodes */}
      <Card>
        <h3 className="text-xl font-bold text-gray-900 mb-4 flex items-center">
          <TrendingUp className="w-5 h-5 mr-2 text-blue-600" />
          Most Connected Objects
        </h3>
        <p className="text-sm text-gray-600 mb-4">
          These objects have the most connections and may require special attention during migration
        </p>

        {insights.most_connected.length === 0 ? (
          <p className="text-gray-500 text-center py-6">No connections found</p>
        ) : (
          <div className="space-y-2">
            {insights.most_connected.map((node, index) => (
              <button
                key={node.node_id}
                onClick={() => {
                  if (onViewFileLineage) {
                    onViewFileLineage(node.node_id);
                  }
                }}
                className="w-full flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-blue-50 transition-colors border-2 border-transparent hover:border-blue-300 cursor-pointer"
                title={`${node.name} - Click to view in lineage graph`}
              >
                <div className="flex items-center space-x-4 flex-1 min-w-0">
                  <div className="flex-shrink-0 w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
                    <span className="text-sm font-bold text-blue-700">#{index + 1}</span>
                  </div>
                  <div className="flex-1 min-w-0 text-left">
                    <p className="font-semibold text-blue-600 hover:text-blue-800 break-words" title={node.name}>{node.name}</p>
                    <p className="text-xs text-gray-500">{getNodeTypeDisplayName(node.type)}</p>
                  </div>
                </div>
                <div className="flex-shrink-0 ml-4">
                  <span className="inline-flex items-center px-4 py-2 rounded-full text-sm font-semibold bg-blue-100 text-blue-800">
                    {node.connection_count} connections
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>

    </div>
  );
}

// Export memoized version for better performance
export default memo(InsightsView);

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: 'blue' | 'green' | 'purple' | 'orange';
}

function StatCard({ icon, label, value, color }: StatCardProps) {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
    orange: 'bg-orange-50 text-orange-600',
  };

  return (
    <Card className="p-6">
      <div className={`inline-flex p-3 rounded-lg mb-3 ${colorClasses[color]}`}>
        {icon}
      </div>
      <p className="text-3xl font-bold text-gray-900 mb-1">{value}</p>
      <p className="text-sm text-gray-600">{label}</p>
    </Card>
  );
}

function getNodeTypeColor(type: string): string {
  const colorMap: Record<string, string> = {
    VIEW: '#8B5CF6',
    TABLE: '#10B981',
    TABLE_OR_VIEW: '#10B981',
    SCRIPT: '#3B82F6',
    FILE: '#F59E0B',
    DATABASE: '#EF4444',
    COLUMN: '#EC4899',
  };
  return colorMap[type.toUpperCase()] || '#6B7280';
}

