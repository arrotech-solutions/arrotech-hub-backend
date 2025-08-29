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
    wget \
    # Basic dependencies for enhanced tools
    libjpeg-dev \
    libffi-dev \
    fonts-liberation \
    fonts-dejavu-core \
    # .NET dependencies
    libc6 \
    libgcc1 \
    libgssapi-krb5-2 \
    libicu67 \
    libssl1.1 \
    libstdc++6 \
    zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install .NET 8 SDK (needed for building from source)
RUN wget https://packages.microsoft.com/config/debian/11/packages-microsoft-prod.deb -O packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && apt-get install -y dotnet-sdk-8.0 \
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

# Copy ACC-MCP source code  
COPY --chown=app:app ACC-MCP/ ./ACC-MCP/

# Build ACC-MCP for Linux
RUN cd ACC-MCP && \
    dotnet restore && \
    dotnet publish -c Release -r linux-x64 --self-contained false -o /app/acc-mcp-published && \
    chmod +x /app/acc-mcp-published/ACC-MCP

# Copy credentials file
COPY --chown=app:app mini-hub-466619-9e3676951f8a.json ./

# Switch to non-root user
USER app

# Expose port
EXPOSE 8000

# Health check with curl
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f https://arrotech-hub.onrender.com/health || exit 1

# Run the application with optimized settings
CMD ["python", "-m", "src.main"] 