FROM python:3.11-slim

WORKDIR /app

# install system dependencies including protobuf compiler
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

# copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy application code
COPY . .

# compile protocol buffers from protos directory
RUN if [ -d "protos" ] && ls protos/*.proto 1> /dev/null 2>&1; then \
        python -m grpc_tools.protoc \
            --python_out=. \
            --grpc_python_out=. \
            --proto_path=protos \
            protos/*.proto; \
    fi

EXPOSE 8080

# health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "server.py"]