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


def _migrate_presets_on_rename(old_id: str, new_id: str) -> dict:
    """Keep every model attached when a provider id changes.

    Rewrites provider references in: global presets.yaml and every agent
    profile's presets.yaml (the scopes _model_config can resolve).
    Preset slots: chat/vision/utility/embedding. Returns per-file counts.
    """
    import glob
    import os

    from helpers import files
    from plugins._model_config.helpers import model_config

    slots = ("chat", "vision", "utility", "embedding")
    counts = {}

    def rewrite(path: str) -> int:
        if not files.exists(path):
            return 0
        presets = model_config._load_presets_from_path(path)
        if not isinstance(presets, list):
            return 0
        changed = 0
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            for slot in slots:
                slot_cfg = preset.get(slot)
                if isinstance(slot_cfg, dict) and slot_cfg.get("provider") == old_id:
                    slot_cfg["provider"] = new_id
                    changed += 1
        if changed:
            files.write_file(path, model_config.yaml_helper.dumps(
                model_config.validate_presets(presets)))
        counts[path] = changed
        return changed

    total = 0
    total += rewrite(model_config._get_presets_path())
    agents_dir = files.get_abs_path(files.USER_DIR, files.AGENTS_DIR)
    if os.path.isdir(agents_dir):
        for profile in os.listdir(agents_dir):
            if os.path.isdir(os.path.join(agents_dir, profile)):
                total += rewrite(files.get_abs_path(agents_dir, profile, files.PLUGINS_DIR, "_model_config", "presets.yaml"))
    return {"total": total, "files": counts}


def _plugin_module():
    from usr.plugins.custom_providers.helpers import custom_providers as cp

    return cp


class CustomProviders(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action") or input.get("op") or "list").strip().lower()
        if action in ("", "get"):
            action = "list"

        cp = _plugin_module()

        if action == "list":
            raw = cp.list_custom()
            custom_ids = set()
            for sec in raw.values():
                if isinstance(sec, dict):
                    custom_ids.update(str(k).lower() for k in sec.keys())
            return {
                "ok": True,
                "custom": raw,
                "custom_ids": sorted(custom_ids),
                "api_key_status": self._key_status(cp, custom_ids),
            }

        if action in ("create", "update", "upsert", "save"):
            payload = input.get("provider") or input.get("data") or input
            ok, err, normalized = cp.validate_payload(payload, is_update=(action == "update"))
            if not ok:
                return Response(status=400, response=err)

            original_id = str(input.get("original_id") or payload.get("original_id") or "").strip().lower()

            # The UI mask (dots) or old placeholder is never a real key
            api_key = str(payload.get("api_key") or payload.get("apiKey") or "").strip()
            if api_key == API_KEY_PLACEHOLDER or cp.is_key_mask(api_key):
                api_key = ""
            # Explicit key removal: "clear the field and save" in the editor
            remove_key = bool(payload.get("remove_key")) and not api_key
            if remove_key:
                dotenv.save_dotenv_value(f"API_KEY_{normalized['id'].upper()}", "")

            # Block accidental duplicates (same name / same api_base under another id,
            # or id collisions with built-in providers)
            try:
                conflicts = cp.find_conflicts(normalized, original_id=original_id)
            except Exception:
                conflicts = []
            if conflicts:
                return Response(status=409, response=" ".join(conflicts))

            try:
                data = cp.upsert_provider(normalized, original_id=original_id)
            except Exception as e:
                return Response(status=500, response=str(e))

            if api_key:
                dotenv.save_dotenv_value(f"API_KEY_{normalized['id'].upper()}", api_key)

            # On rename: migrate the stored API key env var so it keeps working,
            # then blank the old var (its provider id no longer exists).
            migrated = {"total": 0, "files": {}}
            if original_id and original_id != normalized["id"]:
                try:
                    migrated = _migrate_presets_on_rename(original_id, normalized["id"])
                except Exception as e:
                    migrated = {"total": 0, "files": {}, "error": str(e)}
            if original_id and original_id != normalized["id"]:
                old_key = f"API_KEY_{original_id.upper()}"
                new_key = f"API_KEY_{normalized['id'].upper()}"
                if not api_key:
                    old_val = dotenv.get_dotenv_value(old_key)
                    if old_val and not dotenv.get_dotenv_value(new_key):
                        dotenv.save_dotenv_value(new_key, str(old_val))
                try:
                    dotenv.save_dotenv_value(old_key, "")
                except Exception:
                    pass

            return {
                "ok": True,
                "id": normalized["id"],
                "renamed_from": original_id if original_id and original_id != normalized["id"] else "",
                "migrated_presets": migrated,
                "custom": data,
                "api_key_status": self._key_status(cp, cp.get_all_ids()),
                "message": f"Provider '{normalized['name']}' saved.",
            }

        if action == "get_key":
            pid = str(input.get("id") or "").strip().lower()
            if not pid:
                return Response(status=400, response="Missing provider id")
            if pid not in cp.get_all_ids():
                return Response(status=404, response="Unknown custom provider '%s'." % pid)
            return {"ok": True, "id": pid, "key": self._stored_key(pid)}

        if action == "delete":
            pid = str(input.get("id") or input.get("provider_id") or input.get("provider") or "").strip().lower()
            if not pid:
                p = input.get("provider") or {}
                if isinstance(p, dict):
                    pid = str(p.get("id") or "").strip().lower()
            if not pid:
                return Response(status=400, response="Missing provider id for delete")
            try:
                data = cp.delete_provider(pid)
            except ValueError as e:
                return Response(status=400, response=str(e))
            except Exception as e:
                return Response(status=500, response=str(e))

            # env hygiene: blank the key var when no custom provider uses the id anymore
            try:
                if pid not in cp.get_all_ids():
                    dotenv.save_dotenv_value(f"API_KEY_{pid.upper()}", "")
            except Exception:
                pass

            return {
                "ok": True,
                "custom": data,
                "api_key_status": self._key_status(cp, cp.get_all_ids()),
                "message": f"Provider '{pid}' deleted.",
            }

        if action == "test":
            return await self._test_connection(input, request, cp)

        return Response(status=400, response="Unknown action '%s'. Use list|create|update|delete|test|get_key" % action)

    @staticmethod
    def _stored_key(pid: str) -> str:
        try:
            import models

            val = str(models.get_api_key(pid) or "")
            if not val.strip() or val == "None":
                return ""
            return val
        except Exception:
            return ""

    @classmethod
    def _key_status(cls, cp, custom_ids) -> dict:
        return {pid: bool(cls._stored_key(pid)) for pid in sorted(custom_ids)}

    @staticmethod
    def _test_headers(api_key: str, extra_headers: dict) -> dict:
        headers = {"Accept": "application/json"}
        if api_key and api_key != "None":
            headers["Authorization"] = f"Bearer {api_key}"
        for k, v in (extra_headers or {}).items():
            headers[str(k)] = str(v)
        return headers

    async def _test_connection(self, input: dict, request: Request, cp) -> dict | Response:
        """Lightweight connectivity check: GET the resolved /models endpoint."""
        import httpx

        provider = str(input.get("id") or "").strip().lower()
        if provider:
            chat_cfg = cp.get_provider_entry(provider, "chat")
            emb_cfg = cp.get_provider_entry(provider, "embedding")
            cfg = chat_cfg or emb_cfg
            kwargs = (cfg or {}).get("kwargs") or {}
            ml = (cfg or {}).get("models_list") or {}
            # Prefer the values currently shown in the form (user may be testing
            # unsaved edits); fall back to the stored provider config.
            api_base = (
                str(input.get("api_base") or "").strip().rstrip("/")
                or kwargs.get("api_base", "")
            )
            endpoint = (
                str(input.get("models_endpoint") or "").strip()
                or ml.get("endpoint_url", "/models")
            )
            default_base = (
                str(input.get("default_base") or "").strip().rstrip("/")
                or ml.get("default_base", "")
            )
            extra_headers = input.get("extra_headers") or kwargs.get("extra_headers") or {}
            provided_key = str(input.get("api_key") or "").strip()
            if cp.is_key_mask(provided_key) or provided_key == API_KEY_PLACEHOLDER:
                provided_key = ""
        else:
            api_base = str(input.get("api_base") or "").strip().rstrip("/")
            endpoint = str(input.get("models_endpoint") or "/models").strip()
            default_base = str(input.get("default_base") or "").strip().rstrip("/")
            extra_headers = input.get("extra_headers") or {}
            provided_key = str(input.get("api_key") or "").strip()
            if cp.is_key_mask(provided_key) or provided_key == API_KEY_PLACEHOLDER:
                provided_key = ""

        if not api_base and not default_base:
            return Response(status=400, response="Missing API base URL for test")

        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            url = endpoint
        else:
            base = api_base or default_base
            url = base + cp._join_endpoint(base, endpoint)

        if provider and not provided_key:
            provided_key = self._stored_key(provider)

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
