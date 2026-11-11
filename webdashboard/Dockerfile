FROM python:3.11-slim
# Container builds intentionally install as root; keep pip notices build-only.
ARG PIP_ROOT_USER_ACTION=ignore
ARG PIP_DISABLE_PIP_VERSION_CHECK=1
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
WORKDIR /wd
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" requests sqlalchemy "psycopg[binary]" psycopg_pool pandas "numpy<2.4" PyYAML pymodbus
COPY . .
EXPOSE 8503
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8503"]
