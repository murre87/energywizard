FROM python:3.11-slim
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
WORKDIR /wd
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" requests sqlalchemy "psycopg[binary]"
COPY . .
EXPOSE 8503
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8503"]
