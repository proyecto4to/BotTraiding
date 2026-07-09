FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/portfolio-engine/requirements.txt services/portfolio-engine/requirements.txt

WORKDIR /app/services/portfolio-engine
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/portfolio-engine services/portfolio-engine

WORKDIR /app/services/portfolio-engine
EXPOSE 8000
COPY services/portfolio-engine/docker-entrypoint.sh /app/services/portfolio-engine/docker-entrypoint.sh
RUN chmod +x /app/services/portfolio-engine/docker-entrypoint.sh
ENTRYPOINT ["/app/services/portfolio-engine/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
