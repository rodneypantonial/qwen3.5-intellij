FROM ollama/ollama:0.34.4

ENV OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_CONTEXT_LENGTH=8192 \
    OLLAMA_FLASH_ATTENTION=1 \
    OLLAMA_KV_CACHE_TYPE=q8_0 \
    OLLAMA_KEEP_ALIVE=30m \
    MODEL=frob/qwen3.5-instruct:9b \
    WARMUP=true

COPY entrypoint.sh Modelfile /opt/qwen-intellij/
RUN sed -i 's/\r$//' /opt/qwen-intellij/entrypoint.sh /opt/qwen-intellij/Modelfile && chmod +x /opt/qwen-intellij/entrypoint.sh

VOLUME /root/.ollama
EXPOSE 11434

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ollama list >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/opt/qwen-intellij/entrypoint.sh"]
