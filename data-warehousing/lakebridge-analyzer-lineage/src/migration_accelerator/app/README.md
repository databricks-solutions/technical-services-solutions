# Migration Accelerator - Databricks App

## Overview

This is the FastAPI backend for the Migration Accelerator Databricks App. It provides REST API endpoints for:

- **File Upload**: Upload analyzer Excel files
- **Analyzer Operations**: Extract metrics, complexity, and sheet data
- **Lineage Visualization**: Create interactive data lineage graphs
- **LLM Queries**: Ask natural language questions about migration data

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -e ".[app]"

# Set environment variables
export DEBUG=true
export STORAGE_BACKEND=in_memory
export LLM_ENDPOINT=databricks-meta-llama-3-1-70b-instruct

# Run the app
uvicorn migration_accelerator.app.main:app --reload
```

Visit: http://localhost:8080/docs for interactive API documentation

### Production Deployment

See [APP_SETUP.md](../../../docs/APP_SETUP.md) for full deployment guide.

## Architecture

```
app/
├── main.py                 # FastAPI application
├── config.py               # Configuration management
├── api/
│   ├── dependencies.py     # Dependency injection
│   └── routes/
│       ├── upload.py       # File upload endpoints
│       ├── analyzer.py     # Analyzer endpoints
│       ├── lineage.py      # Lineage endpoints
│       └── query.py        # LLM query endpoints
├── models/
│   ├── requests.py         # Request models
│   └── responses.py        # Response models
└── services/
    ├── storage_service.py  # File storage
    ├── analyzer_service.py # Analyzer operations
    ├── lineage_service.py  # Lineage creation
    └── llm_service.py      # LLM integration
```

## API Endpoints

### Core Endpoints

- `POST /api/v1/upload` - Upload analyzer file
- `GET /api/v1/analyzers/{id}` - Get analyzer info
- `GET /api/v1/analyzers/{id}/metrics` - Get metrics
- `GET /api/v1/analyzers/{id}/complexity` - Get complexity
- `POST /api/v1/lineage` - Create lineage visualization
- `GET /api/v1/lineage/{id}/graph` - Get lineage graph data
- `POST /api/v1/query` - Query with LLM

### Utility Endpoints

- `GET /health` - Health check
- `GET /docs` - API documentation

## Configuration

Configure via environment variables (see `.env.example`):

```bash
# App Settings
DEBUG=false
LLM_ENDPOINT=databricks-meta-llama-3-1-70b-instruct

# Storage Settings
STORAGE_BACKEND=unity_catalog  # Options: unity_catalog, in_memory
UC_VOLUME_PATH=/Volumes/migration_accelerator/data/user_files

# API Settings
MAX_UPLOAD_SIZE=104857600  # 100MB
```

## Storage Backends

### Unity Catalog (Recommended for Production)

```python
STORAGE_BACKEND=unity_catalog
UC_VOLUME_PATH=/Volumes/migration_accelerator/data/user_files
```

Files stored at: `/Volumes/migration_accelerator/data/user_files/{user_id}/`

**Benefits:**
- Persistent, governed storage
- Multi-user isolation  
- Audit logging
- Enterprise-grade security

### In-Memory (Development & Testing)

```python
STORAGE_BACKEND=in_memory
```

Files stored at: `/tmp/migration-accelerator/{user_id}/`

**Benefits:**
- No setup required
- Fast for local development
- Automatic cleanup

**Note:** Data is lost on application restart

## Testing

### Unit Tests

```bash
pytest tests/app/
```

### Integration Tests

```bash
# Start test server
uvicorn migration_accelerator.app.main:app --port 8080 &

# Run tests
pytest tests/integration/

# Stop server
kill %1
```

### Manual Testing

```bash
# Upload file
curl -X POST "http://localhost:8080/api/v1/upload" \
  -F "file=@test_data.xlsx" \
  -F "dialect=talend"

# Get metrics
curl "http://localhost:8080/api/v1/analyzers/{id}/metrics"
```

## Dependencies

Core dependencies:
- `fastapi>=0.116.1` - Web framework
- `uvicorn>=0.30.0` - ASGI server
- `pydantic>=2.0.0` - Data validation
- `python-multipart>=0.0.9` - File upload support

Application dependencies:
- `pandas>=2.0.0` - Data processing
- `databricks-sdk>=0.57.0` - Databricks integration
- `langchain>=0.3.0` - LLM orchestration

## Security

- **Authentication**: Currently basic (dev mode). Implement Databricks OAuth for production.
- **File Validation**: File type and size validation on upload
- **Input Sanitization**: All inputs validated via Pydantic models
- **Access Control**: User-based file isolation

## Performance

- **Async Operations**: All I/O operations are async
- **Streaming**: Large file uploads use streaming
- **Caching**: Consider adding caching for repeated queries
- **Rate Limiting**: TODO - Add rate limiting for production

## Monitoring

- **Health Endpoint**: `/health` provides service status
- **Logging**: Structured logging via `utils.logger`
- **Metrics**: TODO - Add Prometheus metrics

## Troubleshooting

### Common Issues

1. **ImportError**: Install app dependencies with `pip install -e ".[app]"`
2. **File Not Found**: Check storage backend configuration and permissions
3. **LLM Errors**: Verify LLM endpoint is accessible and configured correctly

### Debug Mode

Enable debug logging:

```bash
export DEBUG=true
uvicorn migration_accelerator.app.main:app --reload --log-level debug
```

## Contributing

1. Follow existing code structure
2. Add tests for new endpoints
3. Update API documentation
4. Run linting: `make lint`

## License

See LICENSE file in repository root.


