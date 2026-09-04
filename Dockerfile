# dagu-mcp — Dagu Scheduler MCP (FastMCP over HTTP)
#
# Serves MCP tools to list/inspect/create/update/run dagu jobs on the NAS.
# The docker CLI + socket are bind-mounted at runtime (see docker-compose.yml),
# so the image stays slim.
FROM python:3.11-slim

# Link the GHCR package to this repo on push (public repo -> public package).
LABEL org.opencontainers.image.source=https://github.com/nickbrett1/dagu-mcp

RUN pip install --no-cache-dir fastmcp pyyaml

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 3007
CMD ["python", "server.py"]
