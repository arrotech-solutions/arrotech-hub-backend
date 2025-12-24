# Use Python 3.11 slim image with security updates
FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Install system dependencies in one layer
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    # Basic dependencies for enhanced tools
    libjpeg-dev \
    libffi-dev \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user early
RUN useradd --create-home --shell /bin/bash --uid 1000 app

# Create necessary directories with proper permissions
RUN mkdir -p /app/uploads /tmp/uploads && \
    chown -R app:app /app/uploads /tmp/uploads

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with optimizations
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=app:app src/ ./src/

# Note: Credentials should be passed via environment variables, not files
# For Google Cloud, use GOOGLE_APPLICATION_CREDENTIALS with base64-encoded content

# Switch to non-root user
USER app

# Expose port
EXPOSE 8000

# Health check with curl
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application with optimized settings
CMD ["python", "-m", "src.main"] 