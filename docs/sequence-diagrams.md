# Hidden Catch - Sequence Diagrams

## 1. 게임 생성 및 이미지 업로드 플로우

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant N as Nginx
    participant B as Backend (FastAPI)
    participant DB as PostgreSQL
    participant S3 as AWS S3
    participant C as Celery Worker
    participant R as Redis

    U->>F: 이미지 업로드 페이지 접속
    U->>F: 이미지 파일 선택 (최대 3장)
    U->>F: "게임 시작" 버튼 클릭

    F->>N: POST /api/v1/games
    N->>B: 게임 생성 요청
    B->>DB: Game, GameStage, GameUploadSlot 생성 (이미지 개수만큼)
    B->>S3: Presigned URL 생성
    B-->>F: {game_id, upload_slots[]}

    par 이미지마다 병렬
        F->>F: createImageBitmap → 1600px JPEG로 축소 (EXIF 반영)
        F->>S3: PUT presigned_url (수백 KB)
        F->>N: POST /api/v1/games/{game_id}/uploads/complete
        N->>B: 업로드 완료 알림
        B->>DB: slot.uploaded=true, stage.status=waiting_puzzle
        B->>R: Celery Task 전송 (generate_puzzle_for_slot)
        B-->>F: 응답
    end
    opt S3 업로드 실패한 슬롯
        F->>B: POST /uploads/failed {slot}
        B->>DB: stage.status=failed (해당 스테이지 건너뜀)
    end

    C->>R: Task 수신 (generate_puzzle_for_slot)
    Note over C: 퍼즐 생성 파이프라인 (3번 다이어그램)
    C->>DB: Puzzle/Difference 저장, stage=playing, game=playing

    loop 1.5초마다 폴링 (최대 4분)
        F->>N: GET /api/v1/games/{game_id}
        N->>B: 게임 상태 조회
        B-->>F: {status, puzzle, ready_stages, failed_stages}
        F->>U: "AI가 퍼즐을 만들고 있습니다… 1/3 완료"
    end

    F->>F: status="playing" && puzzle 존재 감지
    F->>U: 게임 페이지로 이동 (남은 스테이지는 플레이 중 계속 생성)
```

## 2. 게임 플레이 플로우

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant N as Nginx
    participant B as Backend
    participant DB as PostgreSQL

    U->>F: 게임 페이지 접속
    F->>N: GET /api/v1/games/{game_id}
    N->>B: 게임 데이터 조회
    B->>DB: Game, Puzzle, Difference 조회
    DB-->>B: 게임 데이터
    B-->>N: {puzzle, differences, status}
    N-->>F: 게임 데이터 응답
    
    F->>U: 원본/수정 이미지 표시
    F->>F: 타이머 시작 (3분)
    
    U->>F: 이미지 클릭
    F->>F: 클릭 좌표 계산 (object-fit: contain 보정)
    
    F->>N: POST /api/v1/games/{game_id}/stages/{stage}/check
    N->>B: 답안 확인 요청 {x, y}
    B->>DB: Difference 조회 및 거리 계산
    
    alt 정답 (오차 50px 이내)
        B->>DB: GameStageHit 생성
        B->>DB: current_score 업데이트
        B-->>N: {is_correct: true, found_differences}
        N-->>F: 정답 응답
        F->>U: 빨간 박스 표시
        
        alt 모든 정답 발견
            F->>N: POST /api/v1/games/{game_id}/stages/{stage}/complete
            N->>B: 스테이지 완료 요청
            B->>DB: GameStage 완료 처리
            
            alt 다음 퍼즐 있음
                B->>DB: 다음 Puzzle 조회
                B-->>N: {status: "playing", next_puzzle}
                N-->>F: 다음 스테이지 데이터
                F->>U: 다음 이미지로 전환
            else 마지막 퍼즐
                B->>DB: Game.status = "finished"
                B-->>N: {status: "finished"}
                N-->>F: 게임 종료 응답
                F->>U: 게임 종료 화면 표시
            end
        end
    else 오답
        B-->>N: {is_correct: false}
        N-->>F: 오답 응답
        F->>F: lives -= 1
        F->>U: X 표시 (1초)
        
        alt 목숨 소진 (lives = 0)
            F->>N: POST /api/v1/games/{game_id}/stages/{stage}/complete
            N->>B: 스테이지 완료 (시간 초과)
            B-->>N: 다음 스테이지 또는 게임 종료
            N-->>F: 응답
        end
    end
    
    alt 타이머 만료
        F->>F: 타이머 0초
        F->>N: POST /api/v1/games/{game_id}/stages/{stage}/complete
        N->>B: 스테이지 완료 (시간 초과)
        B-->>N: 다음 스테이지 또는 게임 종료
        N-->>F: 응답
    end
```

## 3. AI 이미지 처리 파이프라인

```mermaid
sequenceDiagram
    participant C as Celery Worker
    participant DB as PostgreSQL
    participant S3 as AWS S3
    participant V as Vision API
    participant G as Gemini Image Model

    Note over C: Task: generate_puzzle_for_slot(slot_id) — 슬롯당 태스크 1개

    C->>DB: GameUploadSlot/Game/GameStage 조회, slot=processing
    C->>S3: GetObject (업로드본)
    C->>C: 정규화: EXIF 보정 → RGB → 긴 변 1024px → 모델 지원 비율로 중앙 크롭
    C->>C: sha256(pixels)

    C->>S3: GetObject puzzle-cache/v1/{sha}/manifest.json
    alt 캐시 히트 (같은 사진을 전에 처리함)
        C->>DB: Puzzle(캐시 키), Difference 저장, stage=playing
    else 캐시 미스
        C->>V: object_localization(1024px JPEG)
        V-->>C: 객체 박스[]
        C->>C: 영역 선택: 40%↑/0.3%↓ 제외, 포함관계 부모 제외, 겹침 처리, 최대 5개
        C->>C: 패딩 → feather 마스크, 번호 박스 힌트 이미지
        C->>G: generate_content(원본 PNG + 힌트 PNG + 편집 지시, image_config 1K)
        Note over G: 기본 gemini-3.1-flash-lite-image<br/>실패 시 gemini-3.1-flash-image로 폴백
        G-->>C: 편집된 이미지 (1K)
        C->>C: 원본 크기로 리사이즈 → 마스크 합성 (마스크 밖 = 원본 픽셀)
        C->>C: 영역별 평균 픽셀 차이 측정 → 바뀌지 않은 영역 제외
        opt 바뀐 영역 0개
            C->>G: 더 강한 프롬프트로 1회 재시도
        end
        C->>C: 검증된 영역만으로 재합성 → original.jpg / modified.jpg
        C->>S3: PutObject ×3 병렬 (original, modified, manifest)
        C->>DB: Puzzle 생성/갱신, Difference(검증된 것만), stage=playing
    end

    C->>DB: Game 상태 갱신 (첫 미완료 스테이지가 playing이면 game=playing)
    Note over C: 실패 시: slot=failed, stage=failed, 모든 스테이지 실패면 game=failed
    Note over C: 로그: puzzle ready … timings={download, normalize, detect, edit_1, composite, upload, total}
```

## 4. 데이터베이스 ER Diagram

```mermaid
erDiagram
    GAME ||--o{ GAME_UPLOAD_SLOT : has
    GAME ||--o{ GAME_STAGE : has
    GAME_UPLOAD_SLOT ||--o| PUZZLE : generates
    PUZZLE ||--o{ DIFFERENCE : contains
    GAME_STAGE ||--|| PUZZLE : uses
    GAME_STAGE ||--o{ GAME_STAGE_HIT : records

    GAME {
        int id PK
        string mode
        string difficulty
        string status
        int current_score
        int current_stage
        timestamp created_at
    }

    GAME_UPLOAD_SLOT {
        int id PK
        int game_id FK
        int slot_number
        string s3_object_key
        boolean uploaded
        json detected_objects
        string analysis_status
    }

    PUZZLE {
        int id PK
        int upload_slot_id FK
        string original_image_url
        string modified_image_url
        int width
        int height
    }

    DIFFERENCE {
        int id PK
        int puzzle_id FK
        string name
        int x
        int y
        int width
        int height
    }

    GAME_STAGE {
        int id PK
        int game_id FK
        int puzzle_id FK
        int stage_number
        boolean completed
        int play_time_milliseconds
    }

    GAME_STAGE_HIT {
        int id PK
        int stage_id FK
        int difference_id FK
        int x
        int y
        timestamp hit_at
    }
```

## 5. 시스템 아키텍처

```mermaid
graph TB
    subgraph "Client"
        Browser[Web Browser]
    end

    subgraph "AWS EC2"
        Nginx[Nginx<br/>Port 80]
        Backend[FastAPI<br/>Port 8000]
        Celery[Celery Worker]
        Redis[Redis<br/>Port 6379]
    end

    subgraph "AWS RDS"
        PostgreSQL[(PostgreSQL)]
    end

    subgraph "AWS S3"
        S3[S3 Bucket<br/>uploads/ + puzzle-cache/]
    end

    subgraph "Google Cloud"
        Vision[Vision API<br/>Object Detection]
        Imagen[Gemini Image Model<br/>gemini-3.1-flash-lite-image]
    end

    Browser -->|HTTP| Nginx
    Nginx -->|Reverse Proxy| Backend
    Nginx -->|Static Files| Browser
    
    Backend -->|SQL| PostgreSQL
    Backend -->|Task Queue| Redis
    Backend -->|Upload/Download| S3
    
    Celery -->|Consume Tasks| Redis
    Celery -->|SQL| PostgreSQL
    Celery -->|Upload/Download| S3
    Celery -->|API Call| Vision
    Celery -->|API Call| Imagen

    style Browser fill:#e1f5ff
    style Nginx fill:#ffe1e1
    style Backend fill:#ffe1e1
    style Celery fill:#ffe1e1
    style Redis fill:#ffe1e1
    style PostgreSQL fill:#e1ffe1
    style S3 fill:#e1ffe1
    style Vision fill:#fff3e1
    style Imagen fill:#fff3e1
```
