"""Otari gateway client — the only way VaultMind talks to a model.

Otari (Mozilla AI) is an OpenAI-compatible LLM gateway. The hosted API
lives at https://api.otari.ai/api/v1 (verified live 2026-11-04; the /v1
path from older blog examples now returns a 404 that says so — the client
surfaces that hint instead of failing opaquely). Auth uses the workspace
API key (`otk_...`) as a Bearer token.

Design rules:
- No API key -> OtariNotConfigured with a clear, actionable message.
  Callers degrade gracefully; nothing here prints a traceback for a
  missing key or a gateway refusal.
- Every response's usage block is returned to the caller so the usage
  ledger can record role / model / tokens / estimated cost.
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

from . import config as cfg

USER_AGENT = "vaultmind/0.1 (otari-hackathon devs-wilding)"


class OtariError(Exception):
    """Gateway returned an error or was unreachable."""

    def __init__(self, message: str, status: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


class OtariNotConfigured(OtariError):
    """No API key configured for the requested role."""


def _safe_int(value: object) -> int:
    """Best-effort int for a gateway usage field; garbage reads as 0."""
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        try:
            return int(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0


class OtariClient:
    def __init__(self, role: str, role_cfg: dict, base_url: str | None = None,
                 timeout: float = 60.0):
        self.role = role
        self.role_cfg = role_cfg
        self.base_url = (base_url or cfg.otari_base_url()).rstrip("/")
        self.timeout = timeout
        self.api_key = cfg.role_api_key(role_cfg)
        if not self.api_key:
            raise OtariNotConfigured(
                f"No Otari API key for role '{role}'. Set OTARI_API_KEY "
                f"(or {role_cfg.get('key_env', 'OTARI_KEY_' + role.upper())}) "
                "in .env — create a key in the Otari.ai dashboard "
                "(workspace -> API Keys -> Generate). See .env.example."
            )

    # -- low level ------------------------------------------------------
    def _read_json(self, resp, path: str) -> dict:
        """Decode a gateway JSON body; malformed bodies are OtariErrors.

        A 200 with an HTML error page or a truncated body used to raise
        a raw ValueError, which the router does not catch — failover
        never engaged and the CLI died. Every malformed response is a
        failed candidate, so it reads as OtariError like any other.
        """
        try:
            data = json.loads(resp.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise OtariError(
                f"Otari gateway returned a malformed response on {path}: "
                f"{exc}") from exc
        if not isinstance(data, dict):
            raise OtariError(
                f"Otari gateway returned a non-object response on {path}: "
                f"{str(data)[:120]}")
        return data

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return self._read_json(resp, path)
        except OtariError:
            raise
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            detail = raw
            try:
                detail = json.loads(raw).get("detail", raw)
            except (ValueError, AttributeError):
                pass
            hint = ""
            if exc.code == 404 and "api/v1" in str(detail):
                hint = (" Hint: the gateway serves its API under /api/v1 — "
                        "check OTARI_BASE_URL.")
            raise OtariError(
                f"Otari gateway HTTP {exc.code} on {path}: {detail}{hint}",
                status=exc.code, detail=str(detail),
            ) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.HTTPException, OSError, ValueError) as exc:
            # Includes http.client.RemoteDisconnected ("Remote end closed
            # connection without response"), which urllib lets escape raw
            # when a server/CDN drops the connection mid-response — that
            # must read as a gateway failure so failover can engage.
            # ValueError covers a malformed base URL ("unknown url type").
            raise OtariError(f"Otari gateway unreachable at {url}: {exc}") from exc

    # -- public API -----------------------------------------------------
    def chat(self, model: str, messages: list[dict],
             temperature: float = 0.2) -> dict:
        """One chat completion. Returns {content, model, usage}."""
        resp = self._post("/chat/completions", {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        })
        choices = resp.get("choices") or []
        if not isinstance(choices, list) or not choices:
            # The Otari routing docs treat an answer with no choices as a
            # failed candidate; surface it the same way so failover applies.
            raise OtariError(f"Otari returned no choices for model {model}",
                             detail=str(resp)[:300])
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") or {}
        if not isinstance(message, dict):
            message = {}
        content = message.get("content", "")
        usage = resp.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        return {
            "content": content if isinstance(content, str) else str(content),
            "model": resp.get("model", model) or model,
            "usage": {
                "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
                "completion_tokens": _safe_int(usage.get("completion_tokens")),
                "total_tokens": _safe_int(usage.get("total_tokens")),
            },
        }

    def list_models(self) -> list[str]:
        """GET /models — used by the smoke test to prove auth + routing."""
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = self._read_json(resp, "/models")
        except OtariError:
            raise
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise OtariError(f"Otari gateway HTTP {exc.code} on /models: {raw[:300]}",
                             status=exc.code, detail=raw[:300]) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.HTTPException, OSError, ValueError) as exc:
            raise OtariError(f"Otari gateway unreachable: {exc}") from exc
        models = data.get("data", [])
        if not isinstance(models, list):
            return []
        return [m["id"] for m in models
                if isinstance(m, dict) and m.get("id")]
