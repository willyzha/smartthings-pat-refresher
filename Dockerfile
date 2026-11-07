FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# Copy project definitions
COPY pyproject.toml README.md ./
COPY rotator/ ./rotator/

# Install rotator dependencies
RUN pip install --no-cache-dir ".[rotator]" && playwright install chromium

# Expose HTTP token server and proxy port
EXPOSE 8765

# Volume mount for session profile and token files
VOLUME ["/app/data"]

# Start the background rotator daemon and token server
CMD ["smartthings-pat-rotator", "serve", "--host", "0.0.0.0", "--port", "8765", "--interval", "20"]
