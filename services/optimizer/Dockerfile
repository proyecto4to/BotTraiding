FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/shared/strategies services/shared/strategies
COPY services/optimizer/requirements.txt services/optimizer/requirements.txt

WORKDIR /app/services/optimizer
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/optimizer services/optimizer

WORKDIR /app/services/optimizer
EXPOSE 8000
COPY services/optimizer/docker-entrypoint.sh /app/services/optimizer/docker-entrypoint.sh
RUN chmod +x /app/services/optimizer/docker-entrypoint.sh
ENTRYPOINT ["/app/services/optimizer/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
