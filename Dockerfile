# --- START OF UPDATED FILE Dockerfile ---
FROM python:3.9-slim

# Set environment variables to prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory inside the container
WORKDIR /app

# Copy requirements.txt and install dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . /app/

# Ensure the start script is executable
RUN chmod +x start.sh

# Command to run when starting the container
CMD ["./start.sh"]
# --- END OF UPDATED FILE Dockerfile ---
