# WhisperFlow — Transcription Server Dockerfile (Card 2)
# Base: NVIDIA CUDA 12.8 on Ubuntu 24.04 (matches DGX Spark Blackwell toolkit)
FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04

# --------------------------------------------------------------------------
# System packages
# --------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        curl \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------------------------------
# Python virtual environment
# --------------------------------------------------------------------------
ENV VENV_PATH=/opt/whisperflow/venv
RUN python3 -m venv $VENV_PATH

# Prepend the venv to PATH so all subsequent python/pip invocations use it
ENV PATH="$VENV_PATH/bin:$PATH"

# --------------------------------------------------------------------------
# Python dependencies
# --------------------------------------------------------------------------
WORKDIR /opt/whisperflow
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# --------------------------------------------------------------------------
# Application code
# --------------------------------------------------------------------------
COPY server.py .

# --------------------------------------------------------------------------
# Runtime configuration defaults (overridable via docker-compose env)
# --------------------------------------------------------------------------
ENV WHISPER_MODEL=large-v3
ENV WHISPER_DEVICE=cuda
ENV WHISPER_COMPUTE=float16
ENV WHISPER_BEAM_SIZE=5
ENV WHISPER_LANGUAGE=en
ENV SERVER_PORT=9876

# HuggingFace cache — mount a host volume here to persist model downloads
ENV HF_HOME=/cache/huggingface

EXPOSE 9876

# --------------------------------------------------------------------------
# Health check — curl the /health endpoint every 30 s
# --------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:9876/health || exit 1

# --------------------------------------------------------------------------
# Start server (single worker — GPU is not thread-safe)
# --------------------------------------------------------------------------
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9876", "--workers", "1"]
