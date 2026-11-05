FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

# The cache mount lives outside the image, so copy instead of hardlinking from it.
ENV UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first: this layer is reused as long as the lock file does not change.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    ANNOUNCER_CONFIG=/config/config.yml

VOLUME ["/config", "/data"]
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["torznab-to-telegram-announcer"]
