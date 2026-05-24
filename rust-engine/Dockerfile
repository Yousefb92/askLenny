# ── Stage 1: Build ────────────────────────────────────────────────────────
FROM rust:1.83-slim AS builder
WORKDIR /app

# Cache dependencies by building a stub binary first.
# This layer only re-runs when Cargo.toml / Cargo.lock change.
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN cargo build --release
RUN rm -rf src

# Build the real source
COPY src ./src
# Touch main.rs so Cargo knows the source changed
RUN touch src/main.rs
RUN cargo build --release

# ── Stage 2: Runtime ──────────────────────────────────────────────────────
FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the compiled binary
COPY --from=builder /app/target/release/KnowledgeGraphDatabase ./lichen-engine

# Copy engine config — users can override this with a bind mount if needed
COPY lichen_config.toml ./

# Data directory — mapped to a Docker volume for persistence
RUN mkdir -p lichen_persistent

EXPOSE 3000
CMD ["./lichen-engine"]
