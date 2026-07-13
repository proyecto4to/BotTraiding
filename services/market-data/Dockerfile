FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/market-data/requirements.txt services/market-data/requirements.txt

WORKDIR /app/services/market-data
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/market-data services/market-data

WORKDIR /app/services/market-data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
