FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/shared/strategies services/shared/strategies
COPY services/strategy-engine/requirements.txt services/strategy-engine/requirements.txt

WORKDIR /app/services/strategy-engine
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/strategy-engine services/strategy-engine

WORKDIR /app/services/strategy-engine
EXPOSE 8000
COPY services/strategy-engine/docker-entrypoint.sh /app/services/strategy-engine/docker-entrypoint.sh
RUN chmod +x /app/services/strategy-engine/docker-entrypoint.sh
ENTRYPOINT ["/app/services/strategy-engine/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
