"""Console entry point (local dev). Databricks Apps typically invoke uvicorn directly."""


def main() -> None:
    import uvicorn

    uvicorn.run(
        "migration_accelerator.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
