MODE = "databricks"
MODULE_NAME = "migration_accelerator"
PERSIST_LOGS = False
USE_AI = True
MAX_CONCURRENT_REQUESTS = 5

# Dialect-specific file extensions mapping
SUPPORTED_DIALECTS = {
    "talend": [".item"],
    "informatica": [".xml", ".pmx"],
    "bteq": [".sh", ".btq"],
    "sql": [".sql"],
    "synapse": [".sql"],
}

SUPPORTED_TARGET_SYSTEMS = [
    "sparksql",
    "pyspark",
    "dbsql",
]
