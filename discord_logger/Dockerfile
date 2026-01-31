FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY log_forwarder.py .

CMD ["python", "-u", "log_forwarder.py"]
