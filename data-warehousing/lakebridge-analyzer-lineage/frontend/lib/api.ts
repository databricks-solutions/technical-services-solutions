/**
 * API client for Migration Accelerator backend
 */

import axios, { AxiosInstance, AxiosError } from 'axios';

// Types
export interface LineageMetadata {
  lineage_id: string;
  format: string;
  sheet_name: string;
  nodes_count?: number;
  edges_count?: number;
  created_at: string;
  auto_generated?: boolean;
}

export interface UploadResponse {
  analyzer_id: string;
  filename: string;
  dialect: string;
  file_size: number;
  sheets: string[];
  created_at: string;
  lineages?: LineageMetadata[];
}

export interface MetricsResponse {
  analyzer_id: string;
  dialect: string;
  metrics: Record<string, any>;
  sheet_name: string;
}

export interface ComplexityResponse {
  analyzer_id: string;
  complexity: Record<string, number>;
  total: number;
  sheet_name: string;
}

export interface AnalyzerResponse {
  analyzer_id: string;
  filename: string;
  dialect: string;
  sheets: string[];
  file_size: number;
  created_at: string;
  metrics?: Record<string, any>;
  complexity?: Record<string, number>;
  lineages?: LineageMetadata[];
}

export interface LineageResponse {
  lineage_id: string;
  analyzer_id: string;
  nodes_count: number;
  edges_count: number;
  node_types: Record<string, number>;
  relationship_types: Record<string, number>;
  enhanced_with_llm: boolean;
  created_at: string;
}

export interface LineageGraphResponse {
  lineage_id: string;
  nodes: Array<{
    id: string;
    name: string;
    type: string;
    properties: Record<string, any>;
  }>;
  edges: Array<{
    source: string;
    target: string;
    relationship: string;
    properties: Record<string, any>;
  }>;
  stats: {
    nodes: {
      total: number;
      by_type: Record<string, number>;
    };
    edges: {
      total: number;
      by_relationship: Record<string, number>;
    };
  };
}

export interface QueryResponse {
  question: string;
  answer: string;
  sources?: string[];
  confidence?: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  storage_backend: string;
  llm_endpoint: string;
}

export interface AggregateLineageResponse {
  nodes: Array<{
    id: string;
    name: string;
    type: string;
    properties: Record<string, any>;
    sources: Array<{
      file_id: string;
      filename: string;
      lineage_id: string;
    }>;
  }>;
  edges: Array<{
    source: string;
    target: string;
    relationship: string;
    properties: Record<string, any>;
    sources: Array<{
      file_id: string;
      filename: string;
      lineage_id: string;
    }>;
  }>;
  stats: {
    total_nodes: number;
    total_edges: number;
    total_files: number;
    files: Array<{
      file_id: string;
      filename: string;
      dialect: string;
      lineage_count: number;
    }>;
    file_dependency_edges?: number;
  };
  compute_time_ms?: number;
  cached?: boolean;
}

export interface LineageInsightsResponse {
  most_connected: Array<{
    node_id: string;
    name: string;
    type: string;
    connection_count: number;
    file_references?: {
      creator_files: Array<{ file_id: string; filename: string }>;
      reads_from_files: Array<{ file_id: string; filename: string }>;
      writes_to_files: Array<{ file_id: string; filename: string }>;
    };
  }>;
  orphaned_nodes: Array<{
    node_id: string;
    name: string;
    type: string;
  }>;
  total_nodes: number;
  total_edges: number;
  node_types: Record<string, number>;
  relationship_types: Record<string, number>;
  total_files: number;
  total_tables: number;
  tables_only_read: Array<{
    node_id: string;
    name: string;
    type: string;
  }>;
  tables_never_read: Array<{
    node_id: string;
    name: string;
    type: string;
  }>;
  temp_tables_filtered?: number;
  global_temp_tables?: number;
}

export interface NodeSearchResponse {
  matched_nodes: Array<{
    id: string;
    name: string;
    type: string;
    properties: Record<string, any>;
    sources: Array<{
      file_id: string;
      filename: string;
      lineage_id: string;
    }>;
  }>;
  paths: Array<{
    matched_node: {
      id: string;
      name: string;
      type: string;
    };
    upstream_nodes: string[];
    downstream_nodes: string[];
    connection_count: number;
    centrality_score: number;
    affected_edges: Array<{
      source: string;
      target: string;
      relationship: string;
    }>;
    nodes_with_roles: Array<{
      id: string;
      name: string;
      type: string;
      node_role: 'matched' | 'upstream' | 'downstream';
      centrality_score?: number;
    }>;
  }>;
}

export interface MigrationOrderResponse {
  waves: Array<{
    wave_number: number;
    nodes: Array<{
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
      source_files: Array<{
        file_id: string;
        filename: string;
        lineage_id: string;
      }>;
    }>;
  }>;
  total_nodes: number;
  has_cycles: boolean;
  cycle_info?: string;
  pre_existing_tables?: Array<{
    table_id: string;
    table_name: string;
    type: string;
    referenced_by_files: string[];
    referencing_file_names: string[];
    read_by_count: number;
    written_by_count: number;
    total_references: number;
  }>;
  table_dependencies?: any;
}

export type ExportFormat = 'json' | 'graphml' | 'gexf' | 'csv';

// API Client Class
class MigrationAcceleratorAPI {
  private client: AxiosInstance;

  constructor(baseURL?: string) {
    this.client = axios.create({
      baseURL: baseURL || process.env.NEXT_PUBLIC_API_URL || '',
      timeout: 300000, // 5 minutes - increased for complex lineage computations
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        console.error('API Error:', error);
        throw error;
      }
    );
  }

  // Health Check
  async healthCheck(): Promise<HealthResponse> {
    const response = await this.client.get<HealthResponse>('/health');
    return response.data;
  }

  // Upload
  async uploadFile(
    file: File, 
    dialect?: string,
    onUploadProgress?: (progressEvent: { loaded: number; total?: number; percentage: number }) => void
  ): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    if (dialect) {
      formData.append('dialect', dialect);
    }

    const response = await this.client.post<UploadResponse>(
      '/api/v1/upload',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          if (onUploadProgress && progressEvent.total) {
            const percentage = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            onUploadProgress({
              loaded: progressEvent.loaded,
              total: progressEvent.total,
              percentage,
            });
          }
        },
      }
    );
    return response.data;
  }

  async listFiles(): Promise<{ files: any[]; count: number }> {
    const response = await this.client.get('/api/v1/upload/files');
    return response.data;
  }

  async deleteFile(fileId: string): Promise<void> {
    await this.client.delete(`/api/v1/upload/${fileId}`);
  }

  // Analyzer
  async getAnalyzer(analyzerId: string): Promise<AnalyzerResponse> {
    const response = await this.client.get<AnalyzerResponse>(
      `/api/v1/analyzers/${analyzerId}`
    );
    return response.data;
  }

  async getMetrics(
    analyzerId: string,
    sheetName: string = 'Summary'
  ): Promise<MetricsResponse> {
    const response = await this.client.get<MetricsResponse>(
      `/api/v1/analyzers/${analyzerId}/metrics`,
      { params: { sheet_name: sheetName } }
    );
    return response.data;
  }

  async getComplexity(
    analyzerId: string,
    sheetName: string = 'Summary'
  ): Promise<ComplexityResponse> {
    const response = await this.client.get<ComplexityResponse>(
      `/api/v1/analyzers/${analyzerId}/complexity`,
      { params: { sheet_name: sheetName } }
    );
    return response.data;
  }

  async getSheetData(
    analyzerId: string,
    sheetName: string
  ): Promise<{ sheet_name: string; data: any[]; count: number }> {
    const response = await this.client.get(
      `/api/v1/analyzers/${analyzerId}/sheets/${sheetName}`
    );
    return response.data;
  }

  // Lineage
  async createLineage(request: {
    analyzer_id: string;
    sheet_name: string;
    format?: string;
    source_column?: string;
    target_column?: string;
    relationship_column?: string;
    script_column?: string;
    enhance_with_llm?: boolean;
    additional_context?: string;
  }): Promise<LineageResponse> {
    const response = await this.client.post<LineageResponse>(
      '/api/v1/lineage',
      request
    );
    return response.data;
  }

  async getLineageGraph(lineageId: string): Promise<LineageGraphResponse> {
    const response = await this.client.get<LineageGraphResponse>(
      `/api/v1/lineage/${lineageId}/graph`
    );
    return response.data;
  }

  async exportLineage(lineageId: string, format: string = 'json'): Promise<any> {
    const response = await this.client.get(
      `/api/v1/lineage/${lineageId}/export`,
      { params: { format } }
    );
    return response.data;
  }

  // Query
  async queryAnalyzer(
    analyzerId: string,
    question: string,
    context?: Record<string, any>
  ): Promise<QueryResponse> {
    const response = await this.client.post<QueryResponse>('/api/v1/query', {
      analyzer_id: analyzerId,
      question,
      context,
    });
    return response.data;
  }

  // Aggregate Lineage
  async getAggregateLineage(includeFileDependencies: boolean = false): Promise<AggregateLineageResponse> {
    const response = await this.client.get<AggregateLineageResponse>(
      '/api/v1/lineage/aggregate',
      { params: { include_file_dependencies: includeFileDependencies } }
    );
    return response.data;
  }

  async getAggregateLineageInsights(): Promise<LineageInsightsResponse> {
    const response = await this.client.get<LineageInsightsResponse>(
      '/api/v1/lineage/aggregate/insights'
    );
    return response.data;
  }

  async getAggregateLineageComplete(includeFileDependencies: boolean = false): Promise<{
    graph: AggregateLineageResponse;
    insights: LineageInsightsResponse;
  }> {
    const response = await this.client.get<{
      graph: AggregateLineageResponse;
      insights: LineageInsightsResponse;
    }>(
      '/api/v1/lineage/aggregate/complete',
      { params: { include_file_dependencies: includeFileDependencies } }
    );
    return response.data;
  }

  async searchAggregateLineage(query: string): Promise<NodeSearchResponse> {
    const response = await this.client.get<NodeSearchResponse>(
      '/api/v1/lineage/aggregate/search',
      { params: { query } }
    );
    return response.data;
  }

  async filterAggregateLineage(fileIds: string[]): Promise<AggregateLineageResponse> {
    const response = await this.client.post<AggregateLineageResponse>(
      '/api/v1/lineage/aggregate/filter',
      fileIds
    );
    return response.data;
  }

  // Migration Order
  async getMigrationOrder(): Promise<MigrationOrderResponse> {
    const response = await this.client.get<MigrationOrderResponse>(
      '/api/v1/lineage/aggregate/migration-order'
    );
    return response.data;
  }

  // Export Aggregate Lineage
  async exportAggregateLineage(format: ExportFormat): Promise<Blob> {
    const response = await this.client.get(
      '/api/v1/lineage/aggregate/export',
      {
        params: { format },
        responseType: 'blob'
      }
    );
    return response.data;
  }

  // Multi-file Query
  async queryMultipleAnalyzers(
    analyzerIds: string[],
    question: string,
    scope: 'single' | 'multiple' | 'all' = 'multiple'
  ): Promise<QueryResponse> {
    const response = await this.client.post<QueryResponse>('/api/v1/query', {
      analyzer_id: analyzerIds[0], // Primary file
      analyzer_ids: analyzerIds,
      question,
      scope,
    });
    return response.data;
  }
}

// Export singleton instance
export const api = new MigrationAcceleratorAPI();

export default api;




