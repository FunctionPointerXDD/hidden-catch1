# 퍼즐 생성 파이프라인 v2 — 아키텍처·설정·운영

연구 배경과 v1 대비 분석은 [ai-pipeline-optimization-research.md](ai-pipeline-optimization-research.md)를 보세요. 이 문서는 **현재 코드가 어떻게 동작하는지**와 **운영자가 만질 수 있는 것**을 정리합니다.

## 1. 구성 요소

| 모듈 | 역할 |
|------|------|
| `app/worker/tasks.py` | Celery 태스크 `generate_puzzle_for_slot(slot_id)`. 다운로드 → `generate_puzzle_images()` → DB 반영. 실패 시 `_mark_failed`. 구 이름 `run_imagen_pipeline`은 호환 alias |
| `app/worker/imaging.py` | Pillow 전용 순수 함수: `normalize_image`, `build_mask`, `composite_edit`, `measure_change`, `draw_region_hints`, `nearest_aspect_ratio` |
| `app/worker/geometry.py` | 탐지 박스 → 정답 영역 선택(`select_difference_rects`) |
| `app/worker/detect.py` | Cloud Vision 탐지(`detect_objects`), Gemini 편집(`edit_image`, 모델 폴백), 프롬프트(`build_edit_prompt`) |
| `app/worker/celery_app.py` | 단일 Celery 앱 (`app/celery_app.py`는 re-export) |
| `app/services/game_service.py` | 상태 전이 규칙 (§4), `uploads/failed` |

## 2. 태스크 흐름

```
generate_puzzle_for_slot(slot_id)
 ├─ [DB 세션 1] slot/game/stage 로드, stage=waiting_puzzle, slot=processing
 ├─ S3 GET 업로드본                                   timings.download
 ├─ generate_puzzle_images()
 │   ├─ normalize: EXIF → RGB → ≤PUZZLE_MAX_EDGE → 비율 크롭   timings.normalize
 │   ├─ sha256(pixels) → puzzle-cache/v1/<sha>/manifest.json  timings.cache_lookup
 │   │     히트 → PuzzleResult(cache_hit=True) 반환
 │   ├─ Vision object_localization(1024px JPEG)            timings.detect
 │   ├─ select_difference_rects: 40%↑/0.3%↓ 제외, 부모 제외, 겹침 처리, ≤5개
 │   ├─ pad_rect(+6%, 최소 feather+2px) → 마스크(feather ≈ 짧은 변 1%)
 │   ├─ 힌트 이미지(번호 박스, 마스크 밖 2·feather+2px)
 │   ├─ edit_image: [원본 PNG, 힌트 PNG, 프롬프트] → Gemini    timings.edit_1 (edit_2)
 │   │     모델 순서: IMAGE_EDIT_MODEL → IMAGE_EDIT_FALLBACK_MODELS
 │   │     각 모델: image_config(비율, 1K) 포함 → 실패 시 image_config 없이 1회 더
 │   ├─ 출력 리사이즈 → 합성 → 영역별 measure_change ≥ MIN_CHANGE만 유지
 │   │     0개면 bold 프롬프트로 재시도(IMAGE_EDIT_MAX_ATTEMPTS) → 여전히 0개면 실패
 │   ├─ 유지 영역만으로 재합성 → original.jpg / modified.jpg (q90)  timings.composite
 │   └─ S3 PUT ×3 병렬 (+manifest.json)                     timings.upload
 ├─ [DB 세션 2] Puzzle/Difference(검증된 것만)/stage=playing/slot=completed, game 상태 갱신
 └─ log: "puzzle ready slot=… cache_hit=… model=… differences=… timings={…}"
```

## 3. 설정 (환경 변수, `app/core/config.py`)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `GCP_PROJECT_ID` | – | Vertex AI 프로젝트 |
| `GCP_LOCATION` | `global` | Gemini 이미지 모델은 global 엔드포인트 사용 |
| `GOOGLE_APPLICATION_CREDENTIALS` | – | 서비스 계정 키 경로 (Vertex AI·Vision 공용) |
| `GOOGLE_API_KEY` | – | 설정 시 Vertex 대신 Gemini Developer API 사용 (편집 단계만) |
| `IMAGE_EDIT_MODEL` | `gemini-3.1-flash-lite-image` | 기본 편집 모델 |
| `IMAGE_EDIT_FALLBACK_MODELS` | `["gemini-3.1-flash-image"]` | JSON 배열. 순서대로 폴백 |
| `IMAGE_EDIT_IMAGE_SIZE` | `1K` | `512px`/`1K`/`2K`/`4K`. Lite는 1K만 지원 |
| `IMAGE_EDIT_SEND_REGION_HINT` | `true` | 번호 박스 힌트 이미지 동봉 |
| `IMAGE_EDIT_MAX_ATTEMPTS` | `2` | 무변화 시 재시도 횟수(총 호출 수) |
| `PUZZLE_MAX_EDGE` | `1024` | 정규화 긴 변(px). 게임 화면(≤500px)의 2배 |
| `PUZZLE_FIT_ASPECT_RATIO` | `true` | 모델 지원 비율로 중앙 크롭 (출력 정렬 보장) |
| `PUZZLE_JPEG_QUALITY` | `90` | 저장 JPEG 품질 |
| `PUZZLE_MAX_DIFFERENCES` | `5` | 정답 영역 최대 개수 |
| `PUZZLE_MIN_AREA_RATIO` | `0.003` | 이 비율보다 작은 객체 제외 |
| `PUZZLE_MIN_CHANGE_SCORE` | `10.0` | 영역 평균 RGB 차이(0~255) 임계값 |
| `PUZZLE_CACHE_ENABLED` | `true` | S3 콘텐츠 주소 캐시 |
| `PUZZLE_CACHE_PREFIX` | `puzzle-cache` | 캐시 S3 프리픽스 |
| `CELERY_CONCURRENCY` (compose) | `3` | 워커 프로세스 수 |

`pydantic-settings`는 리스트 값을 JSON으로 읽습니다: `IMAGE_EDIT_FALLBACK_MODELS='["gemini-3.1-flash-image","gemini-3-pro-image"]'`.

## 4. 상태 머신

```
GameStage.status : waiting_upload → waiting_puzzle → playing → finished
                                  ↘ failed (생성 실패 / 업로드 실패 보고)
GameUploadSlot.analysis_status : pending → processing → completed | failed
Game.status : waiting_upload → playing ⇄ waiting_next_stage → finished
                             ↘ failed (모든 스테이지 실패)
```

규칙 (`game_service.py`, `tasks.refresh_game_status`):
- **현재 스테이지** = `failed`가 아닌 스테이지 중 가장 낮은 번호의 `finished`가 아닌 것. 스테이지 2 퍼즐이 먼저 완성돼도 1을 기다린다.
- `GET /games/{id}`의 `puzzle`은 현재 스테이지가 `playing`이고 퍼즐이 완료된 경우에만 채워진다. 프론트는 `status === 'playing' && puzzle`일 때 이동한다.
- `complete_stage`는 멱등: 이미 `finished`인 스테이지의 `completed_at`을 덮어쓰지 않는다. 다음 스테이지는 `failed`를 건너뛰고, 남은 스테이지가 없으면 `finished`.
- `total_stages`는 `failed`를 제외한 수, `ready_stages`는 `playing|finished` 수, `failed_stages`는 실패 수.

## 5. S3 레이아웃

```
uploads/game-{id}/slot-{n}.png              # 브라우저가 올린 원본(확장자는 고정, 실제는 JPEG일 수 있음)
puzzle-cache/v1/{sha256}/original.jpg       # 정규화 원본 (게임의 "원본 이미지")
puzzle-cache/v1/{sha256}/modified.jpg       # 합성 결과 (게임의 "틀린그림")
puzzle-cache/v1/{sha256}/manifest.json      # width/height/differences/detected/model
uploads/game-{id}/slot-{n}-original.jpg     # PUZZLE_CACHE_ENABLED=false 일 때
uploads/game-{id}/slot-{n}-modified.jpg
```
캐시 무효화: 프리픽스 삭제 또는 `tasks.CACHE_VERSION` 상향. `Difference` 좌표는 정규화 이미지 픽셀 기준이며 `Puzzle.width/height`와 함께 저장된다.

## 6. API 변경

- `GET /api/v1/games/{id}` 응답에 `ready_stages`, `failed_stages` 추가. `status`에 `failed` 가능.
- `POST /api/v1/games/{id}/uploads/failed` `{ "slot": n }` — 브라우저가 S3 업로드에 실패한 슬롯을 건너뛰게 한다 (이미 업로드된 슬롯은 409).
- 기존 엔드포인트의 요청/응답 형식은 그대로.

## 7. 로컬 개발·테스트

```bash
cd src/backend
uv sync                      # .venv 생성 (dev 그룹: pytest, ruff 포함)
.venv/bin/pytest -q          # 외부 API 없이 34개 테스트
.venv/bin/ruff check app tests
```

실제 파이프라인을 로컬에서 돌리려면 `.env`에 DB/S3/GCP 값을 넣고:

```bash
docker compose up -d --build
docker compose logs -f celery | grep -E "puzzle ready|failed"
```

## 8. 튜닝 가이드

| 증상 | 조정 |
|------|------|
| 정답이 1~2개만 남는다 | `PUZZLE_MIN_CHANGE_SCORE` ↓ (8), `IMAGE_EDIT_MODEL=gemini-3.1-flash-image` |
| 바뀐 게 거의 안 보이는 정답이 있다 | `PUZZLE_MIN_CHANGE_SCORE` ↑ (15~20) |
| 너무 작은 객체가 정답이다 | `PUZZLE_MIN_AREA_RATIO` ↑ (0.005) |
| `edit_1`이 15초 이상 | Lite 모델인지 확인, `IMAGE_EDIT_SEND_REGION_HINT=false`로 입력 축소 실험 |
| 합성 경계가 눈에 띈다 | `imaging.feather_radius_for` 비율(1%) ↑ |
| 모델 404/권한 오류 | 프로젝트에서 모델 활성화, `GCP_LOCATION=global`, 폴백 목록 확인 |
| 워커 메모리 부족 | `CELERY_CONCURRENCY` ↓ |
