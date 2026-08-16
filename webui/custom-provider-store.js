import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const API = "plugins/custom_providers/custom_providers";
const MODEL_CONFIG_API = "/plugins/_model_config/model_config_get";

function slugify(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 25);
}

function isValidId(id) {
  return /^[a-z][a-z0-9_]{2,24}$/.test(id);
}

function emptyForm() {
  return {
    type: "chat", // chat | embedding | both
    id: "",
    name: "",
    litellm_provider: "openai",
    api_base: "",
    api_key: "",
    models_endpoint: "/v1/models",
    default_base: "",
    api_key_mode: "required",
    extra_headers_text: "",
    kwargs_text: "",
  };
}

export const store = createStore("customProviders", {
  // state
  customIds: [],
  customRaw: {},
  loading: false,
  saving: false,
  testing: false,
  testResult: "",
  error: "",
  form: emptyForm(),
  _idManuallyEdited: false,
  _editingOriginalId: "", // stored id being edited ("" = create mode)
  _originModel: null, // preset slot object where + / edit was clicked
  _originSelect: null, // provider <select> element in that slot
  _tracked: new Map(), // select element -> { editBtn }

  litellmOptions: [
    { value: "openai", label: "OpenAI compatible (most providers)" },
    { value: "hosted_vllm", label: "hosted_vllm (vLLM)" },
    { value: "openrouter", label: "OpenRouter" },
    { value: "ollama", label: "Ollama" },
    { value: "azure", label: "Azure OpenAI" },
    { value: "anthropic", label: "Anthropic" },
    { value: "gemini", label: "Gemini" },
    { value: "mistral", label: "Mistral" },
    { value: "groq", label: "Groq" },
    { value: "cerebras", label: "Cerebras" },
    { value: "sambanova", label: "Sambanova" },
    { value: "deepseek", label: "DeepSeek" },
    { value: "xai", label: "xAI" },
    { value: "huggingface", label: "HuggingFace" },
    { value: "bedrock", label: "Bedrock" },
    { value: "nvidia_nim", label: "NVIDIA NIM" },
    { value: "cometapi", label: "CometAPI" },
    { value: "moonshot", label: "Moonshot" },
    { value: "nebius", label: "Nebius" },
  ],

  presets: {
    nano_gpt: {
      name: "NanoGPT",
      api_base: "https://nano-gpt.com/api/v1",
      models_endpoint: "/v1/models",
      litellm_provider: "openai",
    },
  },

  init() {
    this.refreshList();
    this._setupInjector();
  },

  _applyList(res) {
    let ids = res?.custom_ids;
    if (!Array.isArray(ids)) {
      ids = [];
      for (const sec of Object.values(res?.custom || {})) {
        if (sec && typeof sec === "object") ids.push(...Object.keys(sec));
      }
    }
    this.customIds = ids;
    this.customRaw = res?.custom || {};
    globalThis.__customProviderIds = new Set(ids.map((s) => String(s).toLowerCase()));
  },

  async refreshList(data) {
    try {
      this.loading = true;
      if (data?.custom) {
        this._applyList(data);
      } else {
        const res = await callJsonApi(API, { action: "list" });
        this._applyList(res);
      }
    } catch (e) {
      console.warn("customProviders list failed", e);
    } finally {
      this.loading = false;
    }
  },

  isCustom(id) {
    if (!id) return false;
    const low = String(id).toLowerCase();
    return this.customIds.map((s) => String(s).toLowerCase()).includes(low);
  },

  // ---- modal helpers ----

  openForType(typeHint = "chat", modelRef = null, selectEl = null) {
    const t = String(typeHint).toLowerCase();
    this.form = emptyForm();
    this.form.type = t === "embedding" ? "embedding" : t === "both" ? "both" : "chat";
    this._idManuallyEdited = false;
    this._editingOriginalId = "";
    this._originModel = modelRef;
    this._originSelect = selectEl;
    this.error = "";
    this.testResult = "";
    this._openModal();
  },

  openForEdit(providerId, modelRef = null, selectEl = null) {
    const pid = String(providerId || "").toLowerCase();
    if (!pid) return;
    this._originModel = modelRef;
    this._originSelect = selectEl;

    const raw = this.customRaw || {};
    const chatEntry = raw?.chat?.[pid] || null;
    const embEntry = raw?.embedding?.[pid] || null;
    const found = chatEntry || embEntry;

    this.form = emptyForm();
    this.testResult = "";
    if (found) {
      this.form.type = chatEntry && embEntry ? "both" : embEntry ? "embedding" : "chat";
      this.form.id = pid;
      this.form.name = found.name || pid;
      this.form.litellm_provider = found.litellm_provider || "openai";
      const kwargs = found.kwargs || {};
      const extra = kwargs.extra_headers || {};
      this.form.api_base = kwargs.api_base || "";
      this.form.models_endpoint = found.models_list?.endpoint_url || "/v1/models";
      this.form.default_base = found.models_list?.default_base || "";
      this.form.api_key_mode = found.api_key_mode || "required";
      this.form.extra_headers_text = Object.entries(extra)
        .map(([k, v]) => `${k}=${v}`)
        .join("\n");
      const rest = { ...kwargs };
      delete rest.api_base;
      delete rest.extra_headers;
      delete rest.a0_api_mode;
      this.form.kwargs_text = Object.entries(rest)
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join("\n");
      this._editingOriginalId = pid;
      this._idManuallyEdited = true;
    } else {
      // entry not loaded yet: open with id prefilled
      this.form.id = pid;
      this._idManuallyEdited = true;
    }
    this.error = "";
    this._openModal();
  },

  onNameInput() {
    if (this._idManuallyEdited) return;
    const s = slugify(this.form.name);
    if (s) this.form.id = s;
  },

  onIdInput() {
    this._idManuallyEdited = true;
    this.form.id = slugify(this.form.id);
  },

  applyPreset(key) {
    const p = this.presets[key];
    if (!p) return;
    this.form.name = p.name;
    this.form.api_base = p.api_base;
    this.form.models_endpoint = p.models_endpoint;
    this.form.litellm_provider = p.litellm_provider;
    if (!this._idManuallyEdited) this.form.id = slugify(p.name);
  },

  _openModal() {
    if (globalThis.openModal) {
      globalThis.openModal("/plugins/custom_providers/webui/custom-provider-modal.html");
    }
  },

  validateForm() {
    if (!this.form.name.trim()) return "Display name is required.";
    if (!isValidId(this.form.id))
      return "ID must be 3-25 chars: starts with letter, a-z 0-9 _ only. Example: nano_gpt";
    if (!this.form.api_base.trim()) return "API base URL is required. Example: https://nano-gpt.com/api/v1";
    if (!(this.form.api_base.startsWith("http://") || this.form.api_base.startsWith("https://")))
      return "API base must start with http:// or https://";
    return "";
  },

  _formToPayload() {
    const extra = {};
    (this.form.extra_headers_text || "").split("\n").forEach((l) => {
      l = l.trim();
      if (!l || l.startsWith("#")) return;
      const i = l.indexOf("=");
      if (i > 0) extra[l.substring(0, i).trim()] = l.substring(i + 1).trim();
    });
    const kwargs = {};
    (this.form.kwargs_text || "").split("\n").forEach((l) => {
      l = l.trim();
      if (!l || l.startsWith("#")) return;
      const i = l.indexOf("=");
      if (i > 0) {
        const k = l.substring(0, i).trim();
        let v = l.substring(i + 1).trim();
        try {
          v = JSON.parse(v);
        } catch {}
        kwargs[k] = v;
      }
    });
    return {
      type: this.form.type,
      id: this.form.id,
      name: this.form.name.trim(),
      litellm_provider: this.form.litellm_provider,
      api_base: this.form.api_base.trim(),
      models_endpoint: this.form.models_endpoint.trim() || "/v1/models",
      default_base: this.form.default_base.trim(),
      api_key_mode: this.form.api_key_mode,
      kwargs,
      extra_headers: extra,
      api_key: this.form.api_key,
    };
  },

  async save() {
    const v = this.validateForm();
    if (v) {
      this.error = v;
      globalThis.justToast?.(v, "error");
      return false;
    }
    this.saving = true;
    this.error = "";
    try {
      const payload = this._formToPayload();
      const originalId =
        this._editingOriginalId && this._editingOriginalId !== payload.id ? this._editingOriginalId : "";
      const res = await callJsonApi(API, {
        action: "upsert",
        provider: payload,
        original_id: originalId,
      });
      this._applyList(res);

      // Update provider dropdowns WITHOUT unmounting the preset editor
      // (flipping modelConfig._loaded would wipe unsaved preset edits).
      await this._syncModelConfigLists();

      // Auto-select the new provider in the slot where + was clicked
      const model = this._originModel;
      const sel = this._originSelect;
      if (sel && sel.isConnected) {
        const current = model?.provider ?? sel.value;
        const shouldRepoint = !current || current === originalId;
        if (shouldRepoint) {
          setTimeout(() => {
            try {
              if ([...sel.options].some((o) => o.value === payload.id)) {
                if (model) model.provider = payload.id;
                else {
                  sel.value = payload.id;
                  sel.dispatchEvent(new Event("change", { bubbles: true }));
                }
              }
            } catch {}
            this._updateEditButton(sel);
            this.updateAllEditButtons();
          }, 80);
        }
      }

      const note = originalId ? ` (renamed from '${originalId}')` : "";
      globalThis.justToast?.(`Provider '${payload.name}' saved${note}`, "success");
      if (globalThis.closeModal) globalThis.closeModal();
      this._editingOriginalId = "";
      return true;
    } catch (e) {
      const msg = e?.message || String(e);
      this.error = msg;
      globalThis.justToast?.(msg, "error");
      return false;
    } finally {
      this.saving = false;
    }
  },

  async deleteCurrent() {
    const pid = this._editingOriginalId || this.form.id;
    if (!pid) return false;
    this.saving = true;
    try {
      const res = await callJsonApi(API, { action: "delete", id: pid });
      this._applyList(res);
      await this._syncModelConfigLists();
      const model = this._originModel;
      const sel = this._originSelect;
      const currentPid = model?.provider ?? sel?.value ?? "";
      if (currentPid === pid) {
        if (model) model.provider = "";
        if (sel?.isConnected) {
          try {
            sel.dispatchEvent(new Event("change", { bubbles: true }));
          } catch {}
        }
      }
      globalThis.justToast?.(`Provider '${pid}' deleted`, "success");
      if (globalThis.closeModal) globalThis.closeModal();
      this._editingOriginalId = "";
      this.updateAllEditButtons();
      return true;
    } catch (e) {
      const msg = e?.message || String(e);
      this.error = msg;
      globalThis.justToast?.(msg, "error");
      return false;
    } finally {
      this.saving = false;
    }
  },

  async test() {
    if (this.testing) return;
    const v = this.validateForm();
    if (v) {
      this.error = v;
      globalThis.justToast?.(v, "error");
      return;
    }
    this.testing = true;
    this.testResult = "";
    try {
      const payload = this._formToPayload();
      const res = await callJsonApi(API, {
        action: "test",
        api_base: payload.api_base,
        models_endpoint: payload.models_endpoint,
        default_base: payload.default_base,
        extra_headers: payload.extra_headers,
        api_key: payload.api_key,
      });
      this.testResult = res?.message || (res?.ok ? "Connected." : "Test failed.");
      globalThis.justToast?.(this.testResult, res?.ok ? "success" : "error");
    } catch (e) {
      this.testResult = e?.message || "Test failed.";
      globalThis.justToast?.(this.testResult, "error");
    } finally {
      this.testing = false;
    }
  },

  // Refresh provider lists in place so open editors keep their state.
  async _syncModelConfigLists() {
    const mc = globalThis.Alpine?.store("modelConfig");
    if (!mc) return;
    try {
      if (!mc._loaded) {
        await mc.ensureLoaded?.();
        return;
      }
      let data;
      if (typeof mc._fetchConfigData === "function") {
        data = await mc._fetchConfigData({});
      } else {
        data = await callJsonApi(MODEL_CONFIG_API, {});
      }
      if (!data) return;

      const chat = data.chat_providers || [];
      const emb = data.embedding_providers || [];
      const spliceIn = (arr, items) => {
        if (Array.isArray(arr) && Array.isArray(items)) arr.splice(0, arr.length, ...items);
      };
      spliceIn(mc.chatProviders, chat);
      spliceIn(mc.embeddingProviders, emb);

      if (data.api_key_status && typeof data.api_key_status === "object") {
        mc.apiKeyStatus = { ...(mc.apiKeyStatus || {}), ...data.api_key_status };
      }

      // key slots for new providers (API Keys page)
      const seen = new Set();
      const keyValues = { ...(mc.apiKeyValues || {}) };
      const keyDirty = { ...(mc.apiKeyDirty || {}) };
      const all = [];
      const allSeen = new Set();
      for (const p of [...chat, ...emb]) {
        if (!p?.value) continue;
        if (!(p.value in keyValues)) keyValues[p.value] = "";
        if (!(p.value in keyDirty)) keyDirty[p.value] = false;
        if (allSeen.has(p.value.toLowerCase())) continue;
        allSeen.add(p.value.toLowerCase());
        all.push({
          value: p.value,
          label: p.label || p.value,
          has_key: !!((data.api_key_status || {})[p.value]),
        });
        seen.add(p.value);
      }
      mc.apiKeyValues = keyValues;
      mc.apiKeyDirty = keyDirty;
      all.sort((a, b) => String(a.label).localeCompare(String(b.label)));
      spliceIn(mc.allProviders, all);
    } catch (e) {
      console.warn("customProviders: modelConfig sync failed", e);
    }
  },

  // ---- injector: + / edit buttons next to provider selects ----

  _updateEditButton(sel) {
    const entry = this._tracked.get(sel);
    if (!entry || !sel.isConnected) return;
    const pid = sel.value;
    const btn = entry.editBtn;
    if (pid && this.isCustom(pid)) {
      btn.style.display = "inline-flex";
      // IMPORTANT: never rewrite the title on every call. The core tooltip store
      // converts title -> Bootstrap tooltip and strips the attribute; rewriting it
      // while the tooltip is shown makes Bootstrap re-show it (DOM mutation), which
      // re-triggers our injector -> infinite observer loop -> page freeze.
      const t = `Edit custom provider '${pid}'`;
      if (entry.lastTitle !== t) {
        entry.lastTitle = t;
        btn.setAttribute("title", t);
      }
    } else {
      btn.style.display = "none";
    }
  },

  updateAllEditButtons() {
    for (const sel of this._tracked.keys()) this._updateEditButton(sel);
  },

  _setupInjector() {
    const typeHintFor = (sel) => {
      const section = sel.closest(".preset-model-section");
      const title = (section?.querySelector(".section-title")?.textContent || "").toLowerCase();
      return title.includes("embedding") ? "embedding" : "chat";
    };
    // the select is bound with x-model="model.provider", so its Alpine scope
    // gives us the preset slot object directly
    const modelRefFor = (el) => {
      try {
        const scope = globalThis.Alpine?.$data?.(el);
        return scope && "model" in scope ? scope.model : null;
      } catch {
        return null;
      }
    };

    const inject = () => {
      document.querySelectorAll('select[x-model="model.provider"]').forEach((sel) => {
        const control = sel.closest(".field-control");
        if (!control || control.querySelector(".cp-provider-actions")) return;

        const typeHint = typeHintFor(sel);

        const actions = document.createElement("div");
        actions.className = "cp-provider-actions";
        actions.style.display = "inline-flex";
        actions.style.gap = "6px";
        actions.style.marginLeft = "8px";
        actions.style.verticalAlign = "middle";

        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.className = "btn btn-small cp-add-btn";
        addBtn.title = "Add custom provider";
        addBtn.innerHTML = '<x-icon name="add" style="font-size:16px"></x-icon>';
        addBtn.style.display = "inline-flex";
        addBtn.style.alignItems = "center";
        addBtn.style.padding = "4px 6px";
        addBtn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.openForType(typeHint, modelRefFor(sel), sel);
        });
        actions.appendChild(addBtn);

        const editBtn = document.createElement("button");
        editBtn.type = "button";
        editBtn.className = "btn btn-small cp-edit-btn";
        editBtn.title = "Edit custom provider";
        editBtn.innerHTML = '<x-icon name="edit" style="font-size:14px"></x-icon>';
        editBtn.style.display = "none";
        editBtn.style.alignItems = "center";
        editBtn.style.padding = "4px 6px";
        editBtn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const pid = sel.value;
          if (pid) this.openForEdit(pid, modelRefFor(sel), sel);
        });
        actions.appendChild(editBtn);

        control.style.display = "flex";
        control.style.alignItems = "center";
        control.style.gap = "6px";
        sel.style.flex = "1 1 auto";
        control.appendChild(actions);

        sel.addEventListener("change", () => this._updateEditButton(sel));
        this._tracked.set(sel, { editBtn, lastTitle: "" });
        this._updateEditButton(sel);
      });

      // prune detached selects and refresh edit-button visibility
      for (const sel of this._tracked.keys()) {
        if (!sel.isConnected) this._tracked.delete(sel);
        else this._updateEditButton(sel);
      }
    };

    const SELECTOR = 'select[x-model="model.provider"]';
    const mutationMatters = (mutations) =>
      mutations.some((m) =>
        Array.from(m.addedNodes).some(
          (n) =>
            n instanceof Element &&
            (n.matches?.(SELECTOR) || n.querySelector?.(SELECTOR))
        )
      );
    const obs = new MutationObserver((mutations) => {
      if (mutationMatters(mutations)) inject();
    });
    obs.observe(document.body, { childList: true, subtree: true });
    // safety net only: skip while tab is hidden, never writes titles needlessly
    setInterval(() => {
      if (!document.hidden) inject();
    }, 1500);
    document.addEventListener("webui-extensions-loaded", inject, { once: true });
    setTimeout(inject, 800);
    setTimeout(inject, 2500);
  },
});
