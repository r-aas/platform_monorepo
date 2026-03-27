# Pre-built mcp-server-kubernetes image.
# Avoids npx downloading ~200MB on every pod start, which races against
# liveness probes and causes CrashLoopBackOff.
FROM node:24-alpine

# Install kubectl — mcp-server-kubernetes shells out to it
RUN apk add --no-cache curl && \
    ARCH=$(uname -m) && \
    case "$ARCH" in \
      aarch64) KARCH=arm64 ;; \
      x86_64) KARCH=amd64 ;; \
      *) KARCH=amd64 ;; \
    esac && \
    curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/${KARCH}/kubectl" -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl && \
    apk del curl

RUN npm install -g mcp-server-kubernetes && \
    npm cache clean --force

EXPOSE 3000

ENTRYPOINT ["mcp-server-kubernetes"]
