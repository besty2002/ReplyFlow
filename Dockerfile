# Python 3.11 이미지 사용
FROM python:3.11-slim

# 환경 변수 설정
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 종속성 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn uvicorn

# 소스 코드 복사
COPY . .

# 실행 권한 부여
RUN chmod +x start.sh

# 기본 실행 (start.sh를 통해 제어)
CMD ["./start.sh"]
