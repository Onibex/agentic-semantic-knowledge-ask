"""Google BigQuery adapter.

Driver: ``google-cloud-bigquery`` (its PEP 249 DB-API at
``google.cloud.bigquery.dbapi``). Install the extra:
``pip install ask-sql-executor[bigquery]``.

Auth is GCP IAM (no host/port/user/pass): service-account key material or
Application Default Credentials. db_config keys: project (required),
credentials_json (service-account JSON *content* — the encrypted-store path,
preferred) | credentials_path (service-account JSON *file path*) | omit both
for ADC, location (dataset region, e.g. 'US'/'EU'), maximum_bytes_billed
(cost cap — queries over the cap fail free).
"""

from __future__ import annotations

import json
import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_bigquery(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against BigQuery and return rows + columns."""
    try:
        from google.cloud import bigquery  # type: ignore[import-not-found]
        from google.cloud.bigquery import dbapi  # type: ignore[import-not-found]

        cfg = request.db_config
        job_config = None
        if cfg.get("maximum_bytes_billed"):
            job_config = bigquery.QueryJobConfig(
                maximum_bytes_billed=int(cfg["maximum_bytes_billed"])
            )

        client_kwargs: dict = {}
        if cfg.get("project"):
            client_kwargs["project"] = cfg["project"]
        if cfg.get("location"):
            client_kwargs["location"] = cfg["location"]
        if job_config is not None:
            client_kwargs["default_query_job_config"] = job_config

        if cfg.get("credentials_json"):
            # Service-account JSON content straight from the encrypted store —
            # no file on disk. Preferred over credentials_path.
            info = json.loads(cfg["credentials_json"])
            client = bigquery.Client.from_service_account_info(info, **client_kwargs)
        elif cfg.get("credentials_path"):
            client = bigquery.Client.from_service_account_json(
                cfg["credentials_path"], **client_kwargs
            )
        else:  # Application Default Credentials
            client = bigquery.Client(**client_kwargs)

        conn = dbapi.connect(client=client)
        try:
            cursor = conn.cursor()
            cursor.execute(request.sql)
            columns = [desc[0] for desc in cursor.description]
            rows = [tuple(r) for r in cursor.fetchall()]
            cursor.close()
        finally:
            conn.close()
        return ExecutionResult(success=True, columns=columns, rows=rows, row_count=len(rows))
    except Exception as exc:  # noqa: BLE001 — adapter boundary
        logger.warning("BigQuery execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
