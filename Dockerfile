FROM python:3.13-slim

WORKDIR /app

# System deps for pandas / yfinance
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Root analyzer dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# FastAPI layer
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY analyzer_core.py llm_processor.py data_layer.py ./
COPY api/ ./api/

ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production

EXPOSE 8000

WORKDIR /app/api
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
