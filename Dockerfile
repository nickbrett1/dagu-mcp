FROM python:3.11-slim

RUN pip install --no-cache-dir fastmcp pyyaml

WORKDIR /app
COPY server.py /app/server.py

# The docker CLI is provided by a bind-mount of the host binary (like the dagu
# container), so the image itself stays slim. Socket is mounted at runtime.

EXPOSE 3007
CMD ["python", "server.py"]
