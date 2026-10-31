FROM python:3.12-slim
RUN pip install --no-cache-dir mpmath==1.3.0
# Native source and exactly one task are copied per run, never baked into image.
WORKDIR /world
