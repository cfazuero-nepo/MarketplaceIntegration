FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN useradd -r -u 10001 appuser
USER 10001

EXPOSE 8080
# --proxy-headers so redirects/URLs respect the ALB's X-Forwarded-* headers
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
