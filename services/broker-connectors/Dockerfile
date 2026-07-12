FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/broker-connectors/requirements.txt services/broker-connectors/requirements.txt

WORKDIR /app/services/broker-connectors
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/broker-connectors services/broker-connectors

WORKDIR /app/services/broker-connectors
EXPOSE 8000
COPY services/broker-connectors/docker-entrypoint.sh /app/services/broker-connectors/docker-entrypoint.sh
RUN chmod +x /app/services/broker-connectors/docker-entrypoint.sh
ENTRYPOINT ["/app/services/broker-connectors/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
