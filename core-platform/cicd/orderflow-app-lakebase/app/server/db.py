"""Lakebase connection pool with per-connection OAuth token minting.

Works both locally (via CLI profile) and in a deployed Databricks App (via the
auto-injected service principal). Tokens are generated fresh whenever the pool
creates or recycles a connection, so nothing expires mid-flight.
"""
import os
import psycopg
from psycopg_pool import ConnectionPool

from .config import get_workspace_client

_w = get_workspace_client()
_ENDPOINT_NAME = os.environ["ENDPOINT_NAME"]


class OAuthConnection(psycopg.Connection):
    """Mints a fresh Lakebase OAuth token for every new connection."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        cred = _w.postgres.generate_database_credential(endpoint=_ENDPOINT_NAME)
        kwargs["password"] = cred.token
        return super().connect(conninfo, **kwargs)


def _pg_user() -> str:
    # Postgres username == the connecting identity. In a deployed app that's the
    # service principal client id (auto-injected as DATABRICKS_CLIENT_ID). Locally
    # it's the signed-in user's email. PGUSER overrides both if explicitly set.
    return (
        os.environ.get("PGUSER")
        or os.environ.get("DATABRICKS_CLIENT_ID")
        or get_workspace_client().current_user.me().user_name
    )


_host = os.environ.get("PGHOST") or os.environ["LAKEBASE_HOST"]
_port = os.environ.get("PGPORT", "5432")
_database = os.environ.get("PGDATABASE", os.environ.get("LAKEBASE_DATABASE", "orderflow"))
_sslmode = os.environ.get("PGSSLMODE", "require")

pool = ConnectionPool(
    conninfo=f"dbname={_database} user={_pg_user()} host={_host} port={_port} sslmode={_sslmode}",
    connection_class=OAuthConnection,
    min_size=1,
    max_size=10,
    max_lifetime=2700,  # recycle before the 1-hour OAuth token expires
    open=False,          # opened in FastAPI lifespan
)


def rows_to_dicts(cur) -> list[dict]:
    """Turn a cursor's result set into a list of dicts keyed by column name."""
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
