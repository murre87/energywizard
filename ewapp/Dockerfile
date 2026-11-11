FROM python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
# Container builds intentionally install as root; keep pip notices build-only.
ARG PIP_ROOT_USER_ACTION=ignore
ARG PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --only-binary=:all: --upgrade pip==26.3 setuptools==84.2.1 wheel==0.46.3
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
WORKDIR /ew
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" requests sqlalchemy "psycopg[binary]" pillow pandas "numpy<2.4" psycopg_pool   # /api/plan importerar smartbox/nordpool.py -> logger.py (pandas) -> settings.py (psycopg_pool); tests/test_ewapp_deps.py
COPY . .
RUN python make_icons.py
EXPOSE 8502
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8502"]
