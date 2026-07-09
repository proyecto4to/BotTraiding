FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/gateway/requirements.txt services/gateway/requirements.txt

WORKDIR /app/services/gateway
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/gateway services/gateway

WORKDIR /app/services/gateway
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
