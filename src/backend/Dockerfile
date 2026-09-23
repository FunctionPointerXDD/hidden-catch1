# Python 3.13 이미지 사용
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# curl은 compose healthcheck에 필요. psycopg[binary]/psycopg2-binary는 휠로
# 설치되므로 gcc/libpq-dev 같은 빌드 도구는 필요 없다 (이미지 ~150MB 절감).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv 설치 (Python 패키지 매니저)
RUN pip install --no-cache-dir uv

# 의존성은 uv.lock에 고정된 버전으로 설치한다 (재현 가능한 빌드).
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
    && uv pip install --system --no-cache -r requirements.txt \
    && rm requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 포트 노출
EXPOSE 8000

# FastAPI 애플리케이션 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
