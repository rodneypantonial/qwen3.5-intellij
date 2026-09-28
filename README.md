# qwen3.5-intellij

Local, GPU-accelerated [Ollama](https://ollama.com) image for **JetBrains AI Assistant**. It generates commit messages (and other quick AI features) with a local **Qwen 3.5 9B** model, so they don't use cloud tokens.

Docker Hub: [`queeryme/qwen3.5-intellij`](https://hub.docker.com/r/queeryme/qwen3.5-intellij)

## What it does

| Feature | Details |
|---|---|
| **Thinking disabled** | Uses [`frob/qwen3.5-instruct:9b`](https://ollama.com/frob/qwen3.5-instruct), a non-thinking build of `qwen3.5:9b`. Answers start immediately instead of after 1,000+ reasoning tokens. |
| **Startup warm-up** | The model is loaded into VRAM when the container starts, so the first commit message is fast. |
| **Idle unload** | The model is unloaded after 30 min idle (`OLLAMA_KEEP_ALIVE=30m`), which frees VRAM and battery. |
| **Tuned for 8 GB VRAM** | 8K context, flash attention and a `q8_0` KV cache keep the model 100% on the GPU. |
| **Pinned Ollama** | Based on `ollama/ollama:0.34.4`, the version it was tested on. |

The model (~6.6 GB) is **not** baked into the image. It's pulled into the `ollama` volume on first start and reused after that.

## Why

With stock `qwen3.5:9b`, IntelliJ's *Generate Commit Message* never returned a result:

1. **Thinking mode is on by default.** qwen3.5 reasons for 20–40 s before it answers, and **AI Assistant cancels local requests after about 10 s**. In the logs this shows as `srv stop: cancel task` after exactly `10.00s`.
2. **The context was too large.** A 64K context set in IntelliJ pushed 27% of the model onto the CPU, which cut speed to about 12 tok/s. At 8K it runs 100% on the GPU at about 52 tok/s.
3. **Cold starts.** Loading the model from disk takes about 45–70 s, so the first request always timed out.

Measured on an RTX 3070 Laptop (8 GB):

| Setup | Commit message latency |
|---|---|
| `qwen3.5:9b`, thinking on, 64K ctx | 80 s+ (cancelled by IntelliJ) |
| `qwen3.5:9b`, thinking on, 8K ctx | 24–40 s (cancelled) |
| **This image (warm)** | **0.2–1 s** |

## Quick start

Requirements: Docker Desktop (WSL 2 backend) with an NVIDIA GPU and a recent driver.

```powershell
docker run -d --gpus all --name ollama --restart unless-stopped `
  -p 11434:11434 -v ollama:/root/.ollama `
  queeryme/qwen3.5-intellij:latest
```

Or with Compose, from this repo:

```powershell
docker compose up -d
```

Check it is ready. The log should show `warm-up done`, and `ollama ps` should show `100% GPU`:

```powershell
docker logs ollama
docker exec ollama ollama ps
```

## IntelliJ setup

1. **Settings → Tools → AI Assistant → Models → Third-party AI providers**
2. Enable **Ollama**, URL `http://localhost:11434`, then **Test Connection**.
3. Under **Local models**, set **Core features** and **Instant helpers** to `frob/qwen3.5-instruct:9b`.
4. If you set a context length in IntelliJ, keep it at **8192** or lower.
5. Optional: enable **Offline mode** so nothing falls back to the cloud.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `MODEL` | `frob/qwen3.5-instruct:9b` | Model to pull and warm up. Use `frob/qwen3.5-instruct:4b` for more speed or less VRAM. |
| `WARMUP` | `true` | Load the model at container start. |
| `OLLAMA_KEEP_ALIVE` | `30m` | Idle time before the model is unloaded. `-1` keeps it loaded forever. |
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Max context. Lower it if `ollama ps` shows a CPU/GPU split. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Lower VRAM use. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Halves KV-cache memory. |

Example: `docker run ... -e MODEL=frob/qwen3.5-instruct:4b -e OLLAMA_KEEP_ALIVE=4h queeryme/qwen3.5-intellij`

## Model choice for 8 GB VRAM

The newer Qwen coding models don't fit in 8 GB:

| Model | Size | 8 GB? |
|---|---|---|
| qwen3.6 / qwen3.8 27B | 18 GB | ❌ needs a 24 GB GPU (RTX 3090/4090) |
| qwen3.6 35B-A3B coding | 23 GB | ❌ needs 32 GB (RTX 5090) |
| qwen3-coder 30B | 19 GB | ❌ |
| **qwen3.5 9B** | 6.6 GB | ✅ best that fits |
| qwen3.5 4B | 3.4 GB | ✅ faster |

## Notes: disabling thinking yourself

If you'd rather build your own no-think model, keep these Ollama 0.34 details in mind:

- `PARAMETER think false` in a Modelfile is **not supported** (see [ollama#14809](https://github.com/ollama/ollama/issues/14809)).
- A custom Modelfile `TEMPLATE` that pre-fills an empty `<think>\n\n</think>` block works, **but** only if:
  - `FROM` points at the GGUF blob, not `qwen3.5:9b`. Otherwise the built-in `RENDERER/PARSER qwen3.5` is inherited and thinking comes back.
  - `OLLAMA_GO_TEMPLATE=1` is set explicitly. Otherwise Ollama prefers the GGUF's embedded (thinking) Jinja template. Look for `template selection ... selected=gguf_chat_template` in the logs.
- Adding `PARSER qwen3.5` without a template drops the chat formatting entirely, and the model rambles for thousands of tokens.

`frob/qwen3.5-instruct` avoids all of this because its GGUF has a non-thinking chat template built in, so it works on stock Ollama.

## Troubleshooting

| Symptom | Fix |
|---|---|
| IntelliJ shows no message; logs show `cancel task` after ~10 s | Model is thinking or loading. Check `ollama ps` and that you selected `frob/qwen3.5-instruct:9b`. |
| `ollama ps` shows e.g. `27%/73% CPU/GPU` | Context too large. Lower it in IntelliJ, or lower `OLLAMA_CONTEXT_LENGTH`. |
| `exec /opt/qwen-intellij/entrypoint.sh: no such file or directory` | CRLF line endings. The Dockerfile strips them; rebuild the image. |
| `--gpus all` fails | Docker Desktop → Settings → General → WSL 2 engine, run `wsl --update`, then restart Docker. |

## Build and publish

```powershell
docker build -t queeryme/qwen3.5-intellij:latest -t queeryme/qwen3.5-intellij:0.34.4-9b .
docker push queeryme/qwen3.5-intellij:latest
docker push queeryme/qwen3.5-intellij:0.34.4-9b
```
