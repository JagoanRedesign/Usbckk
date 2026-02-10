FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create necessary directories
RUN mkdir -p sessions

# Expose ports
EXPOSE 5000
EXPOSE 8000

# Run application
CMD ["python", "main.py"]
