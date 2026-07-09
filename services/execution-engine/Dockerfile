FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/execution-engine/requirements.txt services/execution-engine/requirements.txt

WORKDIR /app/services/execution-engine
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/execution-engine services/execution-engine

WORKDIR /app/services/execution-engine
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
