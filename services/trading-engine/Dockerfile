FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/trading-engine/requirements.txt services/trading-engine/requirements.txt

WORKDIR /app/services/trading-engine
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/trading-engine services/trading-engine

WORKDIR /app/services/trading-engine
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
