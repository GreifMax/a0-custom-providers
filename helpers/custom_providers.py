"""Persistence + validation for custom model providers (plugin-owned YAML)."""

import copy
import os
import re

import yaml
from helpers import cache, files
from helpers import yaml as yaml_helper

PLUGIN_NAME = "custom_providers"
YAML_REL = "conf/model_providers.yaml"

ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,24}$")

VALID_LITELLM_PROVIDERS = {
    "openai",
    "hosted_vllm",
    "ollama",
    "openrouter",
    "azure",
    "anthropic",
    "gemini",
    "mistral",
    "groq",
    "cerebras",
    "sambanova",
    "deepseek",
    "xai",
    "huggingface",
    "bedrock",
    "nvidia_nim",
    "cometapi",
    "moonshot",
    "nebius",
}

VALID_TYPES = {"chat", "embedding", "both"}
VALID_API_KEY_MODES = {"required", "optional", "none"}

API_KEY_MASK_CHARS = {"•", "*"}


def is_key_mask(value: str) -> bool:
    """True when the value is just the UI mask (bullets/asterisks), not a real key."""
    v = str(value or "").strip()
    return bool(v) and set(v) <= API_KEY_MASK_CHARS


def get_builtin_ids() -> set:
    """Provider ids defined by the core (non-plugin) provider config."""
    ids: set = set()
    try:
        base = files.get_abs_path("conf/model_providers.yaml")
        if files.exists(base):
            data = yaml.safe_load(files.read_file(base)) or {}
            for section in (data or {}).values():
                if isinstance(section, dict):
                    ids.update(str(k).lower() for k in section.keys())
    except Exception:
        pass
    return ids


def find_conflicts(normalized: dict, original_id: str = "") -> list:
    """Conflicts that should block saving: id collision with a built-in
    provider, or an existing custom provider with the same display name or
    api_base under a different id (prevents accidental duplicates)."""
    conflicts: list = []
    pid = str(normalized.get("id") or "").lower()
    orig = str(original_id or "").strip().lower()
    data = load_raw()

    if pid and pid in get_builtin_ids():
        conflicts.append(f"ID '{pid}' is already used by a built-in provider. Choose another id.")

    name_low = str(normalized.get("name") or "").strip().lower()
    base_norm = str(normalized.get("api_base") or "").strip().rstrip("/").lower()

    for section in ("chat", "embedding"):
        sec = data.get(section)
        if not isinstance(sec, dict):
            continue
        for other_id, cfg in sec.items():
            oid = str(other_id).lower()
            if oid == pid or (orig and oid == orig):
                continue
            other = cfg or {}
            oname = str(other.get("name") or oid).strip().lower()
            obase = str((other.get("kwargs") or {}).get("api_base") or "").strip().rstrip("/").lower()
            if oname and name_low and oname == name_low:
                conflicts.append(
                    f"A provider named '{other.get('name')}' already exists (id '{oid}'). Use a different display name or edit that provider."
                )
            elif obase and base_norm and obase == base_norm:
                conflicts.append(
                    f"Provider '{other.get('name')}' (id '{oid}') already uses this API base. Edit it instead of creating a duplicate."
                )

    seen: set = set()
    return [c for c in conflicts if not (c in seen or seen.add(c))]




def _yaml_abs() -> str:
    from helpers import plugins as plugins_helper

    plugin_dir = plugins_helper.find_plugin_dir(PLUGIN_NAME)
    if not plugin_dir:
        plugin_dir = files.get_abs_path(files.USER_DIR, files.PLUGINS_DIR, PLUGIN_NAME)
    return files.get_abs_path(plugin_dir, YAML_REL)


def _ensure_conf_dir():
    os.makedirs(os.path.dirname(_yaml_abs()), exist_ok=True)


def load_raw() -> dict:
    abs_path = _yaml_abs()
    if not files.exists(abs_path):
        return {}
    try:
        txt = files.read_file(abs_path)
        if not txt.strip():
            return {}
        data = yaml.safe_load(txt)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_raw(data: dict) -> None:
    """Write YAML and make the running framework pick it up."""
    _ensure_conf_dir()
    files.write_file(_yaml_abs(), yaml_helper.dumps(data))
    try:
        from helpers.providers import reload_providers

        reload_providers()
    except Exception:
        pass
    try:
        cache.clear("*(plugins)*")
        cache.clear("*(api)*")
    except Exception:
        pass


def list_custom() -> dict:
    return load_raw()


def get_all_ids() -> set:
    ids = set()
    for section in load_raw().values():
        if isinstance(section, dict):
            ids.update(str(k).lower() for k in section.keys())
    return ids


def _join_endpoint(api_base: str, endpoint: str) -> str:
    """Avoid double path segments like /api/v1/v1/models.

    model_search joins `base + endpoint` naively, so the stored endpoint must
    not repeat the version segment already present in api_base.
    """
    endpoint = str(endpoint or "").strip()
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    base = str(api_base or "").strip().rstrip("/")
    if not endpoint:
        return "/models" if base.endswith("/v1") else "/v1/models"
    if base:
        base_seg = base.rsplit("/", 1)[-1]
        segs = [s for s in endpoint.strip("/").split("/") if s]
        if segs and segs[0] == base_seg and base_seg:
            segs = segs[1:]
        return "/" + "/".join(segs)
    return endpoint if endpoint.startswith("/") else "/" + endpoint


def normalize_endpoint_url(api_base: str, endpoint: str, default_base: str = "") -> str:
    """Resolve the models endpoint to what model_search will actually request."""
    endpoint = str(endpoint or "").strip()
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    base = str(api_base or default_base or "").strip().rstrip("/")
    return base + _join_endpoint(api_base or default_base, endpoint) if base else endpoint


def validate_payload(payload: dict, is_update: bool = False) -> tuple:
    """Returns (ok, error, normalized)."""
    if not isinstance(payload, dict):
        return False, "Invalid payload", {}

    ptype = str(payload.get("type") or payload.get("provider_type") or "chat").strip().lower()
    if ptype not in VALID_TYPES:
        return False, "Invalid type '%s'. Use chat, embedding or both." % ptype, {}

    pid = str(payload.get("id") or "").strip().lower()
    if not pid:
        name_tmp = str(payload.get("name") or "").strip()
        pid = re.sub(r"[^a-z0-9]+", "_", name_tmp.lower()).strip("_")
    if not pid:
        return False, "Provider id is required (or provide a name to auto-generate it).", {}
    if not ID_RE.match(pid):
        return False, "Provider id must be 3-25 chars: lowercase letter first, then a-z 0-9 _ . Example: nano_gpt", {}

    name = str(payload.get("name") or "").strip()
    if not name:
        return False, "Display name is required.", {}
    if len(name) > 60:
        return False, "Name too long (max 60).", {}

    litellm_provider = str(payload.get("litellm_provider") or "openai").strip().lower()
    if litellm_provider not in VALID_LITELLM_PROVIDERS:
        return False, "Invalid litellm_provider '%s'." % litellm_provider, {}

    api_base = str(payload.get("api_base") or payload.get("apiBase") or "").strip()
    if api_base:
        if not (api_base.startswith("http://") or api_base.startswith("https://")):
            return False, "API base must start with http:// or https://", {}
        api_base = api_base.rstrip("/")
    else:
        return False, "API base URL is required (e.g. https://nano-gpt.com/api/v1).", {}

    models_endpoint = str(
        payload.get("models_endpoint")
        or payload.get("endpoint_url")
        or payload.get("endpointUrl")
        or ""
    ).strip()
    models_endpoint = _join_endpoint(api_base, models_endpoint)

    default_base = str(payload.get("default_base") or payload.get("defaultBase") or "").strip().rstrip("/")
    if default_base and not (default_base.startswith("http://") or default_base.startswith("https://")):
        return False, "Default base must start with http:// or https://", {}

    api_key_mode = str(payload.get("api_key_mode") or payload.get("apiKeyMode") or "required").strip().lower()
    if api_key_mode not in VALID_API_KEY_MODES:
        api_key_mode = "required"

    kwargs = payload.get("kwargs") or {}
    if isinstance(kwargs, str):
        try:
            kwargs = yaml.safe_load(kwargs) or {}
        except Exception:
            kwargs = {}
    if not isinstance(kwargs, dict):
        kwargs = {}

    # never persist secrets inside kwargs
    for k in list(kwargs.keys()):
        if str(k).lower() in {"api_key", "apikey", "api_token", "authorization"}:
            kwargs.pop(k, None)

    extra_headers = payload.get("extra_headers") or {}
    if isinstance(extra_headers, str):
        try:
            extra_headers = yaml.safe_load(extra_headers) or {}
        except Exception:
            extra_headers = {}
    if not isinstance(extra_headers, dict):
        extra_headers = {}
    if extra_headers:
        kwargs["extra_headers"] = extra_headers

    normalized = {
        "id": pid,
        "name": name,
        "litellm_provider": litellm_provider,
        "api_base": api_base,
        "type": ptype,
        "models_endpoint": models_endpoint,
        "default_base": default_base,
        "api_key_mode": api_key_mode,
        "kwargs": kwargs,
    }
    return True, "", normalized


def build_provider_config(normalized: dict, kind: str) -> dict:
    """Build the stored provider config for one section ('chat' or 'embedding')."""
    cfg = {
        "name": normalized["name"],
        "litellm_provider": normalized["litellm_provider"],
    }
    ml = {"endpoint_url": normalized["models_endpoint"], "format": "openai"}
    if normalized["default_base"]:
        ml["default_base"] = normalized["default_base"]
    cfg["models_list"] = ml

    kwargs = copy.deepcopy(normalized.get("kwargs") or {})
    if normalized["api_base"]:
        kwargs["api_base"] = normalized["api_base"]
    if kind == "chat":
        kwargs["a0_api_mode"] = "chat"
    else:
        kwargs.pop("a0_api_mode", None)
    cfg["kwargs"] = kwargs

    if normalized.get("api_key_mode") and normalized["api_key_mode"] != "required":
        cfg["api_key_mode"] = normalized["api_key_mode"]
    return cfg


def _remove_pid(data: dict, pid: str) -> bool:
    found = False
    for section in ("chat", "embedding"):
        if isinstance(data.get(section), dict) and pid in data[section]:
            del data[section][pid]
            if not data[section]:
                del data[section]
            found = True
    return found


def upsert_provider(normalized: dict, original_id: str = "") -> dict:
    """Insert or update a provider. When `original_id` is provided and differs
    from the new id, the old entry is removed in the same atomic save (rename)."""
    pid = normalized["id"]
    data = load_raw()

    orig = str(original_id or "").strip().lower()
    if orig and orig != pid:
        _remove_pid(data, orig)

    ptype = normalized["type"]
    sections = {"chat", "embedding"} if ptype == "both" else {ptype}

    # drop sections this type no longer covers (e.g. both -> chat)
    for section in {"chat", "embedding"} - sections:
        if isinstance(data.get(section), dict) and pid in data[section]:
            del data[section][pid]
            if not data[section]:
                del data[section]

    for section in sections:
        if not isinstance(data.get(section), dict):
            data[section] = {}
        data[section][pid] = build_provider_config(normalized, section)

    save_raw(data)
    return data


def delete_provider(pid: str) -> dict:
    pid = str(pid or "").strip().lower()
    if not pid:
        raise ValueError("Missing provider id")
    data = load_raw()
    if not _remove_pid(data, pid):
        raise ValueError("Provider '%s' not found in custom providers." % pid)
    save_raw(data)
    return data


def get_custom_ids() -> set:
    return get_all_ids()


def get_provider_entry(pid: str, section: str) -> dict:
    data = load_raw()
    return (data.get(section) or {}).get(str(pid or "").lower()) or {}
