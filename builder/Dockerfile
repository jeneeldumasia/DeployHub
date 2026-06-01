FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install pack CLI for Cloud Native Buildpacks
ARG PACK_VERSION=v0.33.2
RUN curl -sSL "https://github.com/buildpacks/pack/releases/download/${PACK_VERSION}/pack-${PACK_VERSION}-linux.tgz" | tar -C /usr/local/bin/ --no-same-owner -xzv pack

# Install Kaniko for Dockerfile fallback builds (rootless/secure)
# Downloading kaniko executor
RUN curl -sSL https://github.com/GoogleContainerTools/kaniko/releases/download/v1.22.0/executor-linux-amd64 -o /usr/local/bin/executor && \
    chmod +x /usr/local/bin/executor

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "main.py"]
