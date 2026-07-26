# LLM Model Inventory

Last checked: 2026-06-12 11:05 Asia/Shanghai

This document records the model providers currently referenced by the project or supplied for runtime use. API keys are intentionally masked.

## Project Wiring

The application uses `aiops/llm/client.py` as the unified OpenAI-compatible client.

| Purpose | Default base URL | Default model | Enabled by default | Key env vars | Notes |
|---|---|---:|---:|---|---|
| Internal-first provider | `http://172.25.60.72:23000/v1` | `deepseek-v4-pro` | No | `INTERNAL_LLM_API_KEY`, `INTERNAL_LLM_API_KEYS` | Used first only when `INTERNAL_LLM_ENABLED=true`. |
| Public fallback provider | `https://api.deepseek.com` | `deepseek-v4-pro` | Yes | `PUBLIC_LLM_API_KEY`, `DEEPSEEK_API_KEY`, `AI_API_KEY` | Current repo examples contain no real official DeepSeek key. |
| Legacy report script | `https://api.deepseek.com` | `deepseek-v4-pro` | N/A | `DEEPSEEK_API_KEY`, `AI_API_KEY` | `scripts/generate_ai_report.py` uses these directly. |

## Tested Providers And Models

| Provider / source | Base URL | Model id | Endpoint type | Key used | Test result | Notes |
|---|---|---|---|---|---|---|
| Official DeepSeek, project public fallback | `https://api.deepseek.com` | `deepseek-v4-pro` | Chat | Not available locally | Not verified | `/v1/models` without a key returned `Authentication Fails (governor)`. Configure `DEEPSEEK_API_KEY`, `AI_API_KEY`, or `PUBLIC_LLM_API_KEY` to test. |
| Branch OneAPI / project internal default | `http://172.25.60.72:23000/v1` | `deepseek-v4-pro` | Chat | `sk-n36...5822` | OK | `/v1/models` lists this model; chat returned `OK`. This is the model currently matching the project's internal default. |
| Branch OneAPI | `http://172.25.60.72:23000/v1` | `qwen2.5-32b` | Chat | `sk-n36...5822` | OK | Listed by `/v1/models`; chat returned `OK`. |
| Branch OneAPI | `http://172.25.60.72:23000/v1` | `qwen3.5-27b` | Chat | `sk-n36...5822` | OK | Listed by `/v1/models`; chat returned `OK`, with reasoning content included in the response. |
| Branch OneAPI | `http://172.25.60.72:23000/v1` | `deepseek-v4-pro-aliyun` | Chat | `sk-n36...5822` | Not available | Chat returned: current group `default` has no channel for this model. It is available on the company modelrouter instead. |
| Internal GPU vLLM | `http://172.25.60.72:8013/v1` | `minicpm` | Vision chat | `7xD9...4hXj` | OK | `/v1/models` lists `minicpm`, root `/home/jsyx/data/models/OpenBMB/MiniCPM-o-4_5`, `max_model_len=2048`; image chat returned a Chinese description. Not wired into the app yet. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `deepseek-v4-pro-tencent` | Chat | `sk-Qcg...Ajsu` | OK | Listed by `/v1/models`; chat returned `OK`. Response `model` field was `deepseek-v4-pro`. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `deepseek-v4-pro-aliyun` | Chat | `sk-Qcg...Ajsu` | OK | Listed by `/v1/models`; chat returned `OK`. Response `model` field was `deepseek-v4-pro`. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `deepseek-v3-2` | Chat | `sk-Qcg...Ajsu` | OK | Listed by `/v1/models`; chat returned `OK`. Response `model` field was `deepseek-v3-2-251201`. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `qwen3.7-max` | Chat | `sk-Qcg...Ajsu` | OK | Listed by `/v1/models`; chat returned `OK`, with reasoning token details. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `glm-5.1-aliyun` | Chat | `sk-Qcg...Ajsu` | OK | Listed by `/v1/models`; chat returned `OK`. Response `model` field was `glm-5.1`. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `qwen-vl-tencent` | Chat / vision chat | `sk-Qcg...Ajsu` | Partial | Text-only chat returned `OK`; image URL chat returned `openai_error / bad_response_status_code`. Treat image capability as unverified. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `bge-m3` | Embeddings | `sk-Qcg...Ajsu` | OK | Listed by `/v1/models`; `/v1/embeddings` returned an embedding vector. |
| Company modelrouter | `http://modelrouter.js96296.com/v1` | `bge-reranker-base` | Rerank | `sk-Qcg...Ajsu` | Not usable via tested route | Listed by `/v1/models` with `rerank`, but `/v1/rerank` returned `Model not found in the model list`. The router may expose rerank through a different path or channel. |

## Recommended Runtime Choices

| Use case | Recommended config | Reason |
|---|---|---|
| Current AIOps text analysis, prefer internal | `INTERNAL_LLM_ENABLED=true`, `INTERNAL_LLM_BASE_URL=http://172.25.60.72:23000/v1`, `INTERNAL_LLM_MODEL=deepseek-v4-pro`, `INTERNAL_LLM_API_KEY=sk-n36...5822` | Matches current code defaults and was verified by chat call. |
| Current AIOps text analysis, broader model choice | `PUBLIC_LLM_BASE_URL=http://modelrouter.js96296.com/v1`, choose `deepseek-v4-pro-tencent`, `deepseek-v4-pro-aliyun`, `qwen3.7-max`, or `glm-5.1-aliyun` | Company router has the largest verified chat model set. |
| Image understanding | Use `http://172.25.60.72:8013/v1`, model `minicpm` | Internal vLLM MiniCPM image chat was verified. |
| Embeddings | Use `http://modelrouter.js96296.com/v1`, model `bge-m3` | Embedding endpoint was verified. |

## Follow-up Items

1. Add real official DeepSeek API key to runtime env if the official public fallback still needs to be validated.
2. Decide whether MiniCPM should be integrated as a separate vision provider; the current unified client assumes text chat.
3. Confirm the intended rerank endpoint for `bge-reranker-base` with the company modelrouter admin.
4. Avoid using `deepseek-v4-pro-aliyun` on `http://172.25.60.72:23000/v1`; it was not available there during this check.
