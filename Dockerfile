# Use official Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy app files
COPY app/ /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variable (required by Cloud Run)
ENV PORT=8080

# Expose the port Cloud Run expects
EXPOSE 8080

# Run the app using Gunicorn
CMD ["gunicorn", "-b", ":8080", "main:app"]