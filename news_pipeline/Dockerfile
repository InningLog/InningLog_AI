FROM python:3.8-slim

# 작업 디렉토리
WORKDIR /app

# 시스템 패키지 
RUN apt-get update && apt-get install -y \
    gcc \
    libxml2-dev \
    libxslt-dev \
    libffi-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY crawler ./crawler
COPY run.py .

# 실행 명령
CMD ["python", "run.py"]