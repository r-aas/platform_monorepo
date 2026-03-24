# Pre-built mcp-server-kubernetes image.
# Avoids npx downloading ~200MB on every pod start, which races against
# liveness probes and causes CrashLoopBackOff.
FROM node:24-alpine

RUN npm install -g mcp-server-kubernetes && \
    npm cache clean --force

EXPOSE 3000

ENTRYPOINT ["mcp-server-kubernetes"]
