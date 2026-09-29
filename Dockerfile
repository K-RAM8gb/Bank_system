# Use a lightweight Python Linux image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Install the system-level Tesseract OCR engine
RUN apt-get update && apt-get install -y tesseract-ocr

# Copy your requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port Render uses
EXPOSE 10000

# The Start Command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]