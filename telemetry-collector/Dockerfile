FROM python:3.11-slim
# Container builds intentionally install as root; keep pip notices build-only.
ARG PIP_ROOT_USER_ACTION=ignore
ARG PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY . .
EXPOSE 8504
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8504"]
