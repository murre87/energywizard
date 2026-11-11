FROM python:3.11-slim
# Container builds intentionally install as root; keep pip notices build-only.
ARG PIP_ROOT_USER_ACTION=ignore
ARG PIP_DISABLE_PIP_VERSION_CHECK=1
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
WORKDIR /ew
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" requests sqlalchemy "psycopg[binary]" pillow pandas "numpy<2.4" psycopg_pool   # /api/plan importerar smartbox/nordpool.py -> logger.py (pandas) -> settings.py (psycopg_pool); tests/test_ewapp_deps.py
COPY . .
RUN python make_icons.py
EXPOSE 8502
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8502"]
