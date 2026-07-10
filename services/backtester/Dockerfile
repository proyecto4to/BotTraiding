FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/shared/strategies services/shared/strategies
COPY services/backtester/requirements.txt services/backtester/requirements.txt

WORKDIR /app/services/backtester
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/backtester services/backtester

WORKDIR /app/services/backtester
EXPOSE 8000
COPY services/backtester/docker-entrypoint.sh /app/services/backtester/docker-entrypoint.sh
RUN chmod +x /app/services/backtester/docker-entrypoint.sh
ENTRYPOINT ["/app/services/backtester/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
