FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/scheduler/requirements.txt services/scheduler/requirements.txt

WORKDIR /app/services/scheduler
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/scheduler services/scheduler

WORKDIR /app/services/scheduler
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
