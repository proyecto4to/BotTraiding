FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/ai-engine/requirements.txt services/ai-engine/requirements.txt

WORKDIR /app/services/ai-engine
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/ai-engine services/ai-engine

WORKDIR /app/services/ai-engine
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
