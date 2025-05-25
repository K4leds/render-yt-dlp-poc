# Start with an official Python slim image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Install ffmpeg (often useful for yt-dlp, e.g., for format conversions or some metadata)
# Install git (yt-dlp sometimes uses it for updates or specific site extractors)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first to leverage Docker's layer caching
COPY requirements.txt .

# Install Python dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container
COPY app.py .

# Inform Docker that the container listens on the port specified by Render's PORT env var
# (defaulting to 8080 in app.py if PORT isn't set)
# This is more for documentation; Render uses the PORT env var to route traffic.
EXPOSE 8080 

# The command to run your Flask application when the container starts
# Render will set the $PORT environment variable, which app.py uses.
CMD ["python", "app.py"]