#!/bin/sh
set -eu

MODEL="${MODEL:-frob/qwen3.5-instruct:9b}"
WARMUP="${WARMUP:-true}"
CUSTOM_MODEL="${CUSTOM_MODEL:-qwen3.5-intellij:9b}"
MODELFILE="${MODELFILE:-/opt/qwen-intellij/Modelfile}"

log() { echo "[entrypoint] $*"; }

ollama serve &
SERVER_PID=$!
trap 'kill -TERM "$SERVER_PID" 2>/dev/null' TERM INT

until ollama list >/dev/null 2>&1; do sleep 1; done
log "ollama server is up"

if ! ollama show "$MODEL" >/dev/null 2>&1; then
  log "pulling $MODEL (first start only)"
  ollama pull "$MODEL"
fi

log "creating $CUSTOM_MODEL from $MODELFILE"
ollama create "$CUSTOM_MODEL" -f "$MODELFILE"

if [ "$WARMUP" = "true" ]; then
  log "warming up $CUSTOM_MODEL"
  ollama run "$CUSTOM_MODEL" "hi" >/dev/null
  log "warm-up done, model is loaded"
fi

wait "$SERVER_PID"
