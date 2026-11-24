FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY nexus ./nexus
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn nexus.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
