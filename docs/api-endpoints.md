# API Endpoints 정리

프론트엔드에서 백엔드 서버로 요청하는 모든 API 엔드포인트 목록입니다.

## 1. 이미지 업로드

### POST `/api/upload-images`

사용자가 업로드한 이미지를 서버로 전송하고, 원본 이미지와 틀린그림 이미지의 URL을 받아옵니다.

**위치**: `src/components/ImageUploadPage.js`

**요청 형식**: `multipart/form-data`

**요청 바디**:
- `images`: 이미지 파일들 (최대 5개, jpg/jpeg/png)
- `sessionId`: 사용자 세션 ID

**응답 예시**:
```json
{
  "images": [
    {
      "original": "https://example.com/original1.jpg",
      "modified": "https://example.com/modified1.jpg"
    },
    {
      "original": "https://example.com/original2.jpg",
      "modified": "https://example.com/modified2.jpg"
    }
  ]
}
```

---

## 2. 게임 시작

### POST `/api/game-start`

게임 시작 시 게임방 ID, 유저 ID, 시작 시각을 서버에 전송합니다.

**위치**: `src/components/ImageUploadPage.js`

**요청 형식**: `application/json`

**요청 바디**:
```json
{
  "gameRoomId": "room_1700123456789",
  "userId": "session_1700123456789_abc123",
  "startTime": "2025-11-16T12:34:56.789Z"
}
```

**응답 예시**:
```json
{
  "success": true,
  "gameRoomId": "room_1700123456789",
  "message": "Game started successfully"
}
```

---

## 3. 답안 확인

### POST `/api/check-answer`

게임 중 사용자가 이미지를 클릭했을 때 해당 좌표가 정답인지 확인합니다.

**위치**: `src/components/GamePage.js`

**요청 형식**: `application/json`

**요청 바디**:
```json
{
  "gameRoomId": "room_1700123456789",
  "userId": "session_1700123456789_abc123",
  "imageUrl": "https://example.com/original1.jpg",
  "x": 0.3456,
  "y": 0.7891,
  "clickTime": "2025-11-16T12:35:30.123Z"
}
```

**응답 예시**:
```json
{
  "gameRoomId": "room_1700123456789",
  "userId": "session_1700123456789_abc123",
  "isCorrect": true,
  "correctCoords": [
    {"x": 0.3456, "y": 0.7891},
    {"x": 0.5678, "y": 0.2345}
  ],
  "end": false,
  "score": 0
}
```

**게임 종료 시 응답 예시**:
```json
{
  "gameRoomId": "room_1700123456789",
  "userId": "session_1700123456789_abc123",
  "isCorrect": true,
  "correctCoords": [
    {"x": 0.3456, "y": 0.7891},
    {"x": 0.5678, "y": 0.2345},
    {"x": 0.1234, "y": 0.9012}
  ],
  "end": true,
  "score": 8500
}
```

---

## 4. 게임 데이터 정리

### POST `/api/cleanup`

게임 종료 후 10분이 지나면 localStorage의 이미지 데이터를 정리하고 서버에 알립니다.

**위치**: `src/components/GamePage.js`

**요청 형식**: `application/json`

**요청 바디**:
```json
{
  "gameRoomId": "room_1700123456789",
  "userId": "session_1700123456789_abc123",
  "imageUrls": [
    "https://example.com/original1.jpg",
    "https://example.com/original2.jpg"
  ]
}
```

**응답 예시**:
```json
{
  "success": true,
  "message": "Cleanup completed"
}
```

---

## 참고 사항

### 좌표 형식
- 모든 좌표는 0~1 사이로 정규화된 소수점 값입니다.
- 소수점 4자리까지 전송됩니다 (예: `0.3456`)
- `x`: 이미지 너비 기준 0(왼쪽) ~ 1(오른쪽)
- `y`: 이미지 높이 기준 0(위) ~ 1(아래)

### 시간 형식
- ISO 8601 형식 사용: `YYYY-MM-DDTHH:mm:ss.sssZ`
- UTC 기준 시간

### 세션 ID
- 첫 접속 시 클라이언트에서 생성
- `localStorage`에 `sessionId` 키로 저장
- 형식: `session_[timestamp]_[random]`

### 게임방 ID
- 게임 시작 시 생성
- `localStorage`에 `currentGameRoomId` 키로 저장
- 형식: `room_[timestamp]`
