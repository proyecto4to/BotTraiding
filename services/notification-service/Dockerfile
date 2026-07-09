FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/notification-service/requirements.txt services/notification-service/requirements.txt

WORKDIR /app/services/notification-service
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/notification-service services/notification-service

WORKDIR /app/services/notification-service
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
