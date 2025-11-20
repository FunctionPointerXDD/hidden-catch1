# HiddenCatch Backend
FastAPI 기반으로 구현된 HiddenCatch 서비스의 백엔드.

## 기술 스택
- Python 3.13
- FastAPI + Uvicorn
- Ruff (포맷터 및 린터)

## 프로젝트 구조
```
src/backend
├── app
│   ├── api
│   │   └── v1
│   │       └── router.py
│   ├── core
│   │   └── config.py
│   └── main.py
├── main.py
├── pyproject.toml
└── README.md
```

## 시작하기
1. **의존성 설치**
   ```bash
   uv sync
   ```

2. **환경 변수 설정**
   - `.env` 파일에 아래와 같이 필요한 값을 정의합니다.
     ```
     DEBUG=True
     DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/hiddencatch
     DATABASE_ECHO=False
     ```
   - 기본적으로 `HiddenCatch API`, `0.1.0`, `development` 값이 설정되어 있으며 필요 시 덮어쓸 수 있습니다.
   - `DATABASE_URL`은 SQLAlchemy 포맷의 PostgreSQL DSN입니다. 필요시 풀 사이즈(`DATABASE_POOL_SIZE`), `DATABASE_MAX_OVERFLOW`, `ALLOWED_ORIGINS` 등을 함께 정의하세요.

3. **서버 실행**
   ```bash
   uvicorn app.main:app --reload
   ```
   - 기본 라우터는 `/api/v1` 프리픽스가 적용됩니다.
   - 헬스 체크: `GET http://localhost:8000/api/v1/healthz`

## TODO
- 실제 도메인 엔드포인트 구현
- DB 모델 및 리포지토리 작성
- 인증/인가 추가
