FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY . .
EXPOSE 8504
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8504"]
