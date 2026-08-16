![Custom Providers](webui/thumbnail.png)

# Custom Providers for Agent Zero

**Add and manage custom OpenAI-compatible model providers directly from the Agent Zero UI — no YAML editing, no server restart.**

A **+** button appears right next to the Provider dropdown in **Settings → Models → Edit Model Presets**. Click it, fill in the base URL and API key, and the provider appears in the dropdown instantly — in every model slot (Main, Utility, Embedding).

---

## Features

- **Add providers from the UI** — OpenAI-compatible endpoints (NanoGPT, vLLM, Ollama, OpenRouter, local servers, …) with their own base URL, API key, and model list endpoint
- **Edit / rename / delete** existing custom providers — including automatic API-key migration on rename
- **Model search** — uses your provider's `/models` endpoint so you can browse models without typing IDs by hand
- **Test connection** — verify the endpoint and key before saving
- **Keys never stored in YAML** — API keys go to your Agent Zero `.env` as `API_KEY_<ID>` (dotenv), same as built-in providers
- **Hot reload** — no server restart: new providers are picked up by the running framework immediately

## How it works

The plugin stores providers in its own `conf/model_providers.yaml` and merges them into the running provider list through Agent Zero's provider configuration, without touching core files. Per-provider config uses the standard Agent Zero provider shape:

```yaml
chat:
  my_provider:
    name: My Provider
    litellm_provider: openai
    models_list:
      endpoint_url: /v1/models
      format: openai
    kwargs:
      api_base: https://my-provider.example.com/v1
      a0_api_mode: chat
```

## Installation

1. Download the plugin (clone this repo or grab the zip) into your Agent Zero **`usr/plugins/`** directory:
   
   ```bash
   git clone https://github.com/GreifMax/a0-vision-sidecar
   cp -r a0-vision-sidecar /a0/usr/plugins/vision_sidecar
   # restart Agent Zero
   ```
   
   or unzip into `/a0/usr/plugins/custom_providers/` and restart Agent Zero.

2. Restart Agent Zero docker instance and the Web UI (CTRL+SHIFT+R).

3. Open **Settings → Models → Edit Model Presets** — a **+** button now appears next to each Provider dropdown.

## Usage

1. In **Edit Model Presets**, click **+** next to a Provider dropdown.
2. Give the provider a **name** (e.g. `My NanoGPT`) — the id is auto-generated.
3. Enter the **API base URL** (e.g. `https://nano-gpt.com/api/v1`).
4. (Optional) Adjust the **models endpoint** — defaults to `/v1/models`.
5. Add the **API key** (stored in `.env`, not in YAML) and hit **Save**.
6. The new provider is selected automatically in the slot where you clicked **+** — finish your preset and save.

> **Tip:** a quick-fill preset for **NanoGPT** is built in (button in the modal).

## API keys

Keys are stored in Agent Zero's dotenv (`.env`) as `API_KEY_<PROVIDER_ID_UPPER>` — e.g. `API_KEY_NANO_GPT`. You can also set them under **Settings → API Keys**. Existing keys survive edits; only a newly entered key is written.

## Security notes

- API keys never land in `model_providers.yaml` or in chat history.
- The connection test only performs a `GET` to the `/models` endpoint with the key as a Bearer token.
- The plugin is read-only with respect to the rest of your Agent Zero install: all state lives in the plugin folder and `.env`.



No core Agent Zero files are modified.

## License

[MIT](LICENSE)
