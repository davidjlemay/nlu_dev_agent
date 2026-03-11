FROM node:20-bookworm-slim

RUN echo "deb http://deb.debian.org/debian bookworm-backports main" \
        >> /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends git python3-pip \
    && apt-get install -y --no-install-recommends -t bookworm-backports \
        python3.12 python3.12-venv python3.12-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH=/app/.venv/bin:$PATH

CMD ["bash"]
