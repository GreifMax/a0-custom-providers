"""API handler for managing custom model providers."""

# This module is executed fresh from disk on every handler-cache miss; evict any
# stale cached copies of the plugin's helper package so edits apply immediately.
try:
    from helpers import modules as _modules

    _modules.purge_namespace("usr.plugins.custom_providers")
except Exception:
    pass

from helpers import dotenv
from helpers.api import ApiHandler, Request, Response

API_KEY_PLACEHOLDER = "************"


class CustomProviders(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action") or input.get("op") or "list").strip().lower()
        if action in ("", "get"):
            action = "list"

        try:
            from usr.plugins.custom_providers.helpers.custom_providers import (
                delete_provider,
                list_custom,
                normalize_endpoint_url,
                upsert_provider,
                validate_payload,
            )
        except Exception as e:
            return Response(status=500, response=f"Import error: {e}")

        if action == "list":
            raw = list_custom()
            custom_ids = set()
            for sec in raw.values():
                if isinstance(sec, dict):
                    custom_ids.update(str(k).lower() for k in sec.keys())
            return {"ok": True, "custom": raw, "custom_ids": sorted(custom_ids)}

        if action in ("create", "update", "upsert", "save"):
            payload = input.get("provider") or input.get("data") or input
            ok, err, normalized = validate_payload(payload, is_update=(action == "update"))
            if not ok:
                return Response(status=400, response=err)

            original_id = str(input.get("original_id") or payload.get("original_id") or "").strip().lower()
            try:
                data = upsert_provider(normalized, original_id=original_id)
            except Exception as e:
                return Response(status=500, response=str(e))

            # Save API key if provided (never the placeholder)
            api_key = str(payload.get("api_key") or payload.get("apiKey") or "").strip()
            if api_key and api_key != API_KEY_PLACEHOLDER:
                dotenv.save_dotenv_value(f"API_KEY_{normalized['id'].upper()}", api_key)

            # On rename: migrate the stored API key env var so it keeps working
            if original_id and original_id != normalized["id"]:
                old_key = f"API_KEY_{original_id.upper()}"
                new_key = f"API_KEY_{normalized['id'].upper()}"
                old_val = dotenv.get_dotenv_value(old_key)
                if old_val and not dotenv.get_dotenv_value(new_key):
                    dotenv.save_dotenv_value(new_key, str(old_val))

            return {
                "ok": True,
                "id": normalized["id"],
                "renamed_from": original_id if original_id and original_id != normalized["id"] else "",
                "custom": data,
                "message": f"Provider '{normalized['name']}' saved.",
            }

        if action == "delete":
            pid = str(input.get("id") or input.get("provider_id") or input.get("provider") or "").strip().lower()
            if not pid:
                p = input.get("provider") or {}
                if isinstance(p, dict):
                    pid = str(p.get("id") or "").strip().lower()
            if not pid:
                return Response(status=400, response="Missing provider id for delete")
            try:
                data = delete_provider(pid)
            except ValueError as e:
                return Response(status=400, response=str(e))
            except Exception as e:
                return Response(status=500, response=str(e))
            return {"ok": True, "custom": data, "message": f"Provider '{pid}' deleted."}

        if action == "test":
            return await self._test_connection(input, request)

        return Response(status=400, response="Unknown action '%s'. Use list|create|update|delete|test" % action)

    @staticmethod
    def _test_headers(api_key: str, extra_headers: dict) -> dict:
        headers = {"Accept": "application/json"}
        if api_key and api_key != "None":
            headers["Authorization"] = f"Bearer {api_key}"
        for k, v in (extra_headers or {}).items():
            headers[str(k)] = str(v)
        return headers

    async def _test_connection(self, input: dict, request: Request) -> dict | Response:
        """Lightweight connectivity check: GET the resolved /models endpoint."""
        import httpx

        provider = str(input.get("id") or "").strip().lower()
        if provider:
            from usr.plugins.custom_providers.helpers.custom_providers import get_provider_entry

            chat_cfg = get_provider_entry(provider, "chat")
            emb_cfg = get_provider_entry(provider, "embedding")
            cfg = chat_cfg or emb_cfg
            kwargs = (cfg or {}).get("kwargs") or {}
            api_base = kwargs.get("api_base", "")
            ml = (cfg or {}).get("models_list") or {}
            endpoint = ml.get("endpoint_url", "/v1/models")
            default_base = ml.get("default_base", "")
            extra_headers = kwargs.get("extra_headers") or {}
            provided_key = ""
        else:
            api_base = str(input.get("api_base") or "").strip().rstrip("/")
            endpoint = str(input.get("models_endpoint") or "/v1/models").strip()
            default_base = str(input.get("default_base") or "").strip().rstrip("/")
            extra_headers = input.get("extra_headers") or {}
            provided_key = str(input.get("api_key") or "").strip()

        if not api_base and not default_base:
            return Response(status=400, response="Missing API base URL for test")

        from usr.plugins.custom_providers.helpers.custom_providers import _join_endpoint

        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            url = endpoint
        else:
            base = api_base or default_base
            url = base + _join_endpoint(base, endpoint)

        if provider and not provided_key:
            try:
                import models

                provided_key = str(models.get_api_key(provider) or "")
            except Exception:
                provided_key = ""

        headers = self._test_headers(provided_key, extra_headers)
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                count = ""
                try:
                    body = resp.json()
                    if isinstance(body, dict) and isinstance(body.get("data"), list):
                        count = f" ({len(body['data'])} models)"
                except Exception:
                    pass
                return {"ok": True, "url": url, "message": f"Connected{count}.", "status": 200}
            if resp.status_code in (401, 403):
                return {
                    "ok": False,
                    "url": url,
                    "status": resp.status_code,
                    "message": f"Endpoint reachable but returned HTTP {resp.status_code} — check the API key.",
                }
            return {
                "ok": False,
                "url": url,
                "status": resp.status_code,
                "message": f"Endpoint returned HTTP {resp.status_code}.",
            }
        except Exception as e:
            return {"ok": False, "url": url, "message": f"Connection failed: {e}"}
