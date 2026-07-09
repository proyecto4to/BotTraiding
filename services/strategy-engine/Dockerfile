FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/strategy-engine/requirements.txt services/strategy-engine/requirements.txt

WORKDIR /app/services/strategy-engine
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/strategy-engine services/strategy-engine

WORKDIR /app/services/strategy-engine
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
