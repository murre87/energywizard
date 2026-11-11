FROM python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
# Container builds intentionally install as root; keep pip notices build-only.
ARG PIP_ROOT_USER_ACTION=ignore
ARG PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --only-binary=:all: --upgrade pip==26.3 setuptools==84.2.1 wheel==0.46.3
WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY . .
EXPOSE 8504
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8504"]
