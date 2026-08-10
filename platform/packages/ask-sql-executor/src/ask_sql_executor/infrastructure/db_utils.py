import psycopg2
from dotenv import load_dotenv


# ──────────────────────────────────────────────────
# PostgreSQL
# ──────────────────────────────────────────────────
def _pg_sslmode(config: dict) -> str:
    """Return sslmode from config, defaulting to 'prefer' (works with and without SSL)."""
    return config.get("sslmode", "prefer")


def test_postgresql_connection(config: dict) -> tuple[bool, str]:
    """Test PostgreSQL connection"""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
            sslmode=_pg_sslmode(config),
            connect_timeout=5,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return True, f"Connection successful: {version[:50]}..."

    except psycopg2.OperationalError as e:
        return False, f"Connection error: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


# ──────────────────────────────────────────────────
# SAP HANA Cloud
# ──────────────────────────────────────────────────
def test_hana_connection(config: dict) -> tuple[bool, str]:
    """Test SAP HANA Cloud connection via hdbcli"""
    try:
        from hdbcli import dbapi  # type: ignore
    except ImportError:
        return False, "hdbcli not installed. Run: pip install hdbcli"

    try:
        conn = dbapi.connect(
            address=config["host"],
            port=int(config["port"]),
            user=config["user"],
            password=config["password"],
            encrypt=True,
            sslValidateCertificate=False,
            communicationTimeout=10000,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT VERSION FROM SYS.M_DATABASE")
        version = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return True, f"HANA Cloud connection successful. Version: {version}"

    except Exception as e:
        return False, f"HANA connection error: {str(e)}"


def get_hana_connection(config: dict):
    """Return an open hdbcli connection. Sets currentSchema when configured."""
    from hdbcli import dbapi  # type: ignore

    kwargs: dict = dict(
        address=config["host"],
        port=int(config["port"]),
        user=config["user"],
        password=config["password"],
        encrypt=True,
        sslValidateCertificate=False,
    )
    if config.get("schema"):
        kwargs["currentSchema"] = config["schema"]
    return dbapi.connect(**kwargs)


# ──────────────────────────────────────────────────
# Generic connection test (lite multi-DB, 2026-07)
# ──────────────────────────────────────────────────
# For the new backends (Snowflake / Databricks / ClickHouse / SQL Server /
# Db2 / BigQuery / Fabric) the connection test reuses the execution ADAPTER —
# it runs a trivial probe query through the exact same code path chat uses, so
# a green test means chat can actually connect. HANA / PostgreSQL keep their
# dedicated testers above (richer version strings).
_PROBE_SQL = {
    "db2": "SELECT 1 FROM SYSIBM.SYSDUMMY1",
}


def test_connection(db_type: str, config: dict) -> tuple[bool, str]:
    """Test any supported backend. Dispatches to the dedicated HANA/PG testers,
    else runs a probe SELECT through the registered execution adapter."""
    if db_type == "postgresql":
        return test_postgresql_connection(config)
    if db_type == "hana":
        return test_hana_connection(config)

    from ..domain.models import ExecutionRequest
    from .registry import get_adapter, supported_db_types

    adapter = get_adapter(db_type)
    if adapter is None:
        return False, f"No execution adapter for db_type={db_type!r} (have: {supported_db_types()})"

    probe = _PROBE_SQL.get(db_type, "SELECT 1")
    result = adapter(ExecutionRequest(sql=probe, db_type=db_type, db_config=config))
    if result.success:
        return True, f"{db_type} connection successful."
    return False, f"{db_type} connection error: {result.error}"


# ──────────────────────────────────────────────────
# OpenSearch
# ──────────────────────────────────────────────────
def test_opensearch_connection(config: dict) -> tuple[bool, str]:
    """Test OpenSearch connection via opensearch-py."""
    try:
        from opensearchpy import OpenSearch  # type: ignore
    except ImportError:
        return False, "opensearch-py not installed. Run: pip install opensearch-py"

    try:
        host = config.get("host", "localhost")
        port = int(config.get("port", 9200))
        username = config.get("username", "")
        password = config.get("password", "")
        use_ssl = bool(config.get("use_ssl", False))
        verify_certs = bool(config.get("verify_certs", False))

        kwargs: dict = dict(
            hosts=[{"host": host, "port": port}],
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
        )
        if username and password:
            kwargs["http_auth"] = (username, password)

        client = OpenSearch(**kwargs)
        info = client.info()
        version = info.get("version", {}).get("number", "unknown")
        cluster = info.get("cluster_name", "unknown")
        return True, f"OpenSearch connection successful. Cluster: {cluster}, Version: {version}"

    except Exception as e:
        return False, f"OpenSearch connection error: {str(e)}"


# ──────────────────────────────────────────────────
# SAP Cloud Identity Services (IAS)
# ──────────────────────────────────────────────────
def test_ias_connection(config: dict) -> tuple[bool, str]:
    """
    Test connection to SAP Cloud Identity Services via SCIM API.
    Calls GET /scim/v2/ServiceProviderConfig with Basic Auth.
    """
    import requests

    url = config.get("url", "").rstrip("/")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    if not all([url, client_id, client_secret]):
        return False, "Missing IAS URL, Client ID or Client Secret"

    try:
        resp = requests.get(
            f"{url}/scim/v2/ServiceProviderConfig",
            auth=(client_id, client_secret),
            timeout=10,
        )
        if resp.status_code == 200:
            return True, f"IAS connection successful. Tenant: {url}"
        elif resp.status_code == 401:
            return False, "Authentication failed — check Client ID and Client Secret"
        else:
            return False, f"IAS returned HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"IAS connection error: {str(e)}"


# ──────────────────────────────────────────────────
# SAP AI Core
# ──────────────────────────────────────────────────
def test_sap_ai_core_connection(config_path: str) -> tuple[bool, str]:
    """Test SAP AI Core connection"""
    try:
        import os

        from gen_ai_hub.proxy.core.proxy_clients import get_proxy_client

        load_dotenv(override=True)
        os.environ["AICORE_CONFIG"] = os.path.abspath(config_path)

        proxy_client = get_proxy_client("gen-ai-hub")
        deployments = proxy_client.get_deployments()

        if deployments:
            return True, f"Connection successful. {len(deployments)} deployment(s) available."
        else:
            return False, "Connection successful but no deployments available."

    except FileNotFoundError:
        return False, f"Configuration file not found: {config_path}"
    except Exception as e:
        error_msg = str(e)
        if "invalid_client" in error_msg or "Bad credentials" in error_msg:
            return False, "Invalid credentials. Please check your .env file and aicore_config.json"
        return False, f"Connection error: {error_msg}"
