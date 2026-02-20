"""
Main FastAPI application for Migration Accelerator.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from migration_accelerator.app.api.routes import analyzer, lineage, query, upload
from migration_accelerator.app.config import settings
from migration_accelerator.app.models.responses import ErrorResponse, HealthResponse
from migration_accelerator.utils.logger import get_logger

log = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    log.info("Starting Migration Accelerator API")
    log.info(f"Storage backend: {settings.storage_backend}")
    log.info(f"LLM endpoint: {settings.llm_endpoint}")

    yield

    # Shutdown
    log.info("Shutting down Migration Accelerator API")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="API for migration assessment and lineage visualization",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    log.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=str(exc), type=type(exc).__name__, detail="Internal server error"
        ).dict(),
    )


# Health check endpoint
@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        storage_backend=settings.storage_backend.value,
        llm_endpoint=settings.llm_endpoint,
    )


# Include API routers
app.include_router(upload.router, prefix=settings.api_prefix)
app.include_router(analyzer.router, prefix=settings.api_prefix)
app.include_router(lineage.router, prefix=settings.api_prefix)
app.include_router(query.router, prefix=settings.api_prefix)


# Serve static frontend files (Next.js export)
# In Databricks Apps, Next.js export outputs to frontend/.next/out (via distDir config)
# This must be mounted last to allow API routes to take precedence
frontend_dir = Path(__file__).parent.parent.parent.parent / "frontend" / ".next" / "out"

if frontend_dir.exists():
    log.info(f"Serving static frontend from: {frontend_dir}")
    
    # Mount static files (non-HTML) if _next directory exists
    next_static_dir = frontend_dir / "_next"
    if next_static_dir.exists():
        app.mount(
            "/_next",
            StaticFiles(directory=str(next_static_dir)),
            name="next_static",
        )
    
    # Catch-all route for serving frontend (must be last)
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve frontend static files with fallback to index.html for SPA routing."""
        # Handle root path
        if full_path == "" or full_path == "/":
            index_path = frontend_dir / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
        
        # Try to serve specific file
        file_path = frontend_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        
        # Fallback to index.html for client-side routing
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        
        return JSONResponse(
            status_code=404,
            content={"error": "Frontend not found", "detail": "Frontend build not available"},
        )
else:
    log.warning(f"Frontend directory not found: {frontend_dir}")
    log.warning("API-only mode - frontend will not be served")
    
    # Provide API info endpoint when frontend is not available
    @app.get("/", tags=["root"])
    async def root():
        """Root endpoint - API info."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health",
        }


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Run Migration Accelerator API")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Set logging level",
    )
    parser.add_argument(
        "--timeout-keep-alive",
        type=int,
        default=300,
        help="Keep-alive timeout in seconds",
    )

    args = parser.parse_args()

    # Set environment variables based on arguments
    if args.debug:
        os.environ["DEBUG"] = "true"

    if args.log_level:
        os.environ["LOG_LEVEL"] = args.log_level.upper()

    log.info(
        f"Starting server on {args.host}:{args.port} (debug={args.debug}, log_level={args.log_level.upper()})"
    )
    log.info(
        f"Keep-alive timeout set to {args.timeout_keep_alive}s for long-running requests"
    )

    # Run uvicorn with extended timeouts for long-running background jobs
    uvicorn.run(
        "migration_accelerator.app.main:app",
        host=args.host,
        port=args.port,
        reload=args.debug,
        timeout_keep_alive=args.timeout_keep_alive,
        timeout_graceful_shutdown=30,
    )




