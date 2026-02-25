FROM python:3.9-slim 
WORKDIR /app


RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libi2c-dev \
    gcc \
    i2c-tools \
    libxcb1\
    libglib2.0-0\
    libsm6\
    libxrender-dev\
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir opencv-python-headless


COPY . .
CMD ["python","-u", "main.py"]
