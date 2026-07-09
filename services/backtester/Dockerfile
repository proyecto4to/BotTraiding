FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/backtester/requirements.txt services/backtester/requirements.txt

WORKDIR /app/services/backtester
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/backtester services/backtester

WORKDIR /app/services/backtester
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
