FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/risk-engine/requirements.txt services/risk-engine/requirements.txt

WORKDIR /app/services/risk-engine
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/risk-engine services/risk-engine

WORKDIR /app/services/risk-engine
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
