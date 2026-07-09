FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/auth-service/requirements.txt services/auth-service/requirements.txt

WORKDIR /app/services/auth-service
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/auth-service services/auth-service

WORKDIR /app/services/auth-service
EXPOSE 8000
COPY services/auth-service/docker-entrypoint.sh /app/services/auth-service/docker-entrypoint.sh
RUN chmod +x /app/services/auth-service/docker-entrypoint.sh
ENTRYPOINT ["/app/services/auth-service/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
