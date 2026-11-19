# Minimal Dockerfile for isolated unit test execution sandbox
FROM python:3.10-slim

# Prevent writing .pyc files to disk and unbuffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install only pytest
RUN pip install --no-cache-dir pytest

# Create a non-root user (UID 1000)
RUN useradd -m -u 1000 -s /bin/bash sandboxuser

# Create sandbox working directory
RUN mkdir -p /sandbox && chown -R 1000:1000 /sandbox

USER 1000:1000
WORKDIR /sandbox

CMD ["pytest", "-v"]

