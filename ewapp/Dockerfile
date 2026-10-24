FROM python:3.11-slim
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
WORKDIR /ew
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" requests sqlalchemy "psycopg[binary]" pillow
COPY . .
RUN python make_icons.py
EXPOSE 8502
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8502"]
