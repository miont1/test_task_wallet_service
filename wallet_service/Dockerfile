FROM python:3.11-slim

WORKDIR /app/wallet_service

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/wallet_service

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m wallet_service.scripts.seed && uvicorn wallet_service.main:app --host 0.0.0.0 --port 8000"]
