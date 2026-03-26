# Open Ontologies MCP server — built from local source for ARM64.
# Build context must be the cloned repo: docker build -f <this> ~/work/clones/mcp/open-ontologies/
FROM rust:1-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev build-essential clang && \
    rm -rf /var/lib/apt/lists/*

ENV CARGO_INCREMENTAL=0 CARGO_PROFILE_RELEASE_DEBUG=0

WORKDIR /build
COPY . .
RUN cargo build --release && strip target/release/open-ontologies

FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libssl3 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/target/release/open-ontologies /usr/local/bin/open-ontologies
RUN open-ontologies init

EXPOSE 8080

ENTRYPOINT ["open-ontologies", "serve-http", "--host", "0.0.0.0", "--port", "8080"]
