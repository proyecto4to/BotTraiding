FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/paper-trading/requirements.txt services/paper-trading/requirements.txt

WORKDIR /app/services/paper-trading
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/paper-trading services/paper-trading

WORKDIR /app/services/paper-trading
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
