FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc libsqlite3-dev \
    && pip install --no-cache-dir appworld==0.1.3.post1 \
    && appworld install \
    && rm -rf /var/lib/apt/lists/*
# Deliberately contains installed apps, but no benchmark data or task labels.
ENV APPWORLD_ROOT=/world
