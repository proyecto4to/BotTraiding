FROM python:3.11-slim

WORKDIR /app

COPY services/shared/contracts services/shared/contracts
COPY services/autonomy-controller/requirements.txt services/autonomy-controller/requirements.txt

WORKDIR /app/services/autonomy-controller
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY services/autonomy-controller services/autonomy-controller

WORKDIR /app/services/autonomy-controller
EXPOSE 8000
COPY services/autonomy-controller/docker-entrypoint.sh /app/services/autonomy-controller/docker-entrypoint.sh
RUN chmod +x /app/services/autonomy-controller/docker-entrypoint.sh
ENTRYPOINT ["/app/services/autonomy-controller/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
