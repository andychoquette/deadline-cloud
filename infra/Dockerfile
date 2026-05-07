FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /src/deadline-cloud
RUN pip install --no-cache-dir '/src/deadline-cloud[mcp]'

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1',8000)); s.close()" || exit 1

ENTRYPOINT ["deadline", "mcp-server"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--auth-mode", "oauth-delegation"]
