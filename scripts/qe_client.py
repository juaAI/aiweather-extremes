"""Thread-safe, content-addressed-cached client for the query-engine
station-benchmark endpoints.

Every request/response pair is cached under ``data/cache/<sha256>.json`` and
appended to ``data/cache/manifest.jsonl`` so the full extraction is
reproducible and re-runs are free. Designed for parallel extraction: one
``requests.Session`` per thread, a lock only around manifest appends, and
cache writes via atomic rename.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# scripts/ lives one level below the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "data" / "cache"

# Extraction requires query-service credentials; rebuilding from the included
# compact aggregates does not.
QE_BASE_URL = os.environ.get("QE_BASE_URL", "")
API_KEY = os.environ.get("QE_API_KEY", "")

TIMEOUT_S = 300.0


class QEError(RuntimeError):
    def __init__(self, status: int, path: str, detail: str):
        super().__init__(f"HTTP {status} on {path}: {detail[:500]}")
        self.status = status


class QEClient:
    """Cached QE client. Safe to share across threads."""

    def __init__(
        self,
        base_url: str = QE_BASE_URL,
        api_key: str = API_KEY,
        cache_dir: Path = CACHE_DIR,
    ):
        if not base_url or not api_key:
            raise RuntimeError(
                "Extraction requires query-service access: set QE_BASE_URL and "
                "QE_API_KEY. The included aggregates data reproduces all "
                "tables and figures without API access."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.cache_dir / "manifest.jsonl"
        self._manifest_lock = threading.Lock()
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"X-API-Key": self.api_key})
            self._local.session = session
        return session

    @staticmethod
    def _key(method: str, path: str, payload: dict | None, params: dict | None) -> str:
        canonical = json.dumps(
            {"method": method, "path": path, "payload": payload, "params": params},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        params: dict | None = None,
        max_retries: int = 4,
    ) -> Any:
        key = self._key(method, path, payload, params)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text())["response"]

        last_error: Exception | None = None
        for attempt in range(max_retries):
            started = time.monotonic()
            try:
                resp = self._session().request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                    params=params,
                    timeout=TIMEOUT_S,
                )
                if resp.status_code >= 400:
                    # 5xx are retried below; 4xx are deterministic client errors.
                    raise QEError(resp.status_code, path, resp.text)
                data = resp.json()
                elapsed = round(time.monotonic() - started, 2)
                tmp = cache_file.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
                tmp.write_text(json.dumps({"response": data}))
                tmp.rename(cache_file)
                with self._manifest_lock, self.manifest_path.open("a") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "key": key,
                                "method": method,
                                "path": path,
                                "payload": payload,
                                "params": params,
                                "status": resp.status_code,
                                "elapsed_s": elapsed,
                                "fetched_at": datetime.now(timezone.utc).strftime(
                                    "%Y-%m-%dT%H:%M:%SZ"
                                ),
                            }
                        )
                        + "\n"
                    )
                return data
            except QEError as exc:
                if exc.status < 500:
                    raise
                last_error = exc
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"request failed after {max_retries} retries: {last_error}")

    # -- Endpoint helpers ---------------------------------------------------

    def metrics(
        self,
        *,
        models: list[str],
        geo: dict | None = None,
        station_ids: list[str] | None = None,
        start_time: str,
        end_time: str,
        variables: list[str],
        metrics: list[str],
        max_lead_minutes: int,
        debias: bool,
        obs_buckets: bool = False,
        init_hours: list[int] | None = None,
    ) -> dict:
        payload: dict = {
            "models": models,
            "start_time": start_time,
            "end_time": end_time,
            "variables": variables,
            "metrics": metrics,
            "max_prediction_timedelta_minutes": max_lead_minutes,
            "debias": debias,
        }
        if obs_buckets:
            payload["obs_buckets"] = True
        if geo is not None:
            payload["geo"] = geo
        if station_ids is not None:
            payload["station_ids"] = station_ids
        if init_hours:
            payload["init_hours"] = init_hours
        return self.request("POST", "/v1/station-benchmarks/metrics", payload=payload)

    def available_dates(self, model: str, days_lookback: int = 365) -> list[str]:
        data = self.request(
            "GET",
            "/v1/station-benchmarks/available-dates",
            params={"model": model, "days_lookback": days_lookback},
        )
        return data["dates"]
