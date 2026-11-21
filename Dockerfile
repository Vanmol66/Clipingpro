FROM python:3.10-slim

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirement definitions first
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy all project code
COPY . .

# Create persistent storage directories
RUN mkdir -p downloads clips

# Expose HTTP port
EXPOSE 5000

ENV PORT=5000
ENV PYTHONUNBUFFERED=1

# Run with Gunicorn WSGI server
CMD ["gunicorn", "app:app", "--workers", "2", "--timeout", "300", "--bind", "0.0.0.0:5000"]
