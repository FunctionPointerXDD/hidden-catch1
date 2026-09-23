import React, { useState, useEffect, useRef } from 'react';
import './ImageUploadPage.css';

const MAX_IMAGES = 3;
// 서버는 퍼즐 이미지를 긴 변 1024px로 정규화한다. 그 이상의 해상도는 업로드
// 시간만 늘리므로 브라우저에서 먼저 줄여서 보낸다 (여유를 두어 1600px).
const UPLOAD_MAX_EDGE = 1600;
const UPLOAD_JPEG_QUALITY = 0.9;
const KEEP_ORIGINAL_UNDER_BYTES = 1.5 * 1024 * 1024;
const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 4 * 60 * 1000;

/**
 * 업로드 전에 사진을 브라우저에서 축소한다.
 * - EXIF 회전을 반영해 픽셀을 바로 세운다 (서버 정규화와 동일한 결과)
 * - 긴 변 UPLOAD_MAX_EDGE px, JPEG 재인코딩 → 수 MB 사진이 수백 KB로 줄어든다
 * - 실패하면 원본 파일을 그대로 올린다 (서버가 어차피 정규화한다)
 */
async function prepareImageForUpload(file) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const { width, height } = bitmap;
    const longest = Math.max(width, height);
    if (longest <= UPLOAD_MAX_EDGE && file.size <= KEEP_ORIGINAL_UNDER_BYTES) {
      bitmap.close();
      return file;
    }
    const scale = Math.min(1, UPLOAD_MAX_EDGE / longest);
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', UPLOAD_JPEG_QUALITY)
    );
    if (!blob) return file;
    const baseName = file.name.replace(/\.[^.]+$/, '') || 'image';
    return new File([blob], `${baseName}.jpg`, { type: 'image/jpeg' });
  } catch (error) {
    console.warn('이미지 축소에 실패해 원본을 업로드합니다:', error);
    return file;
  }
}

async function postJson(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function ImageUploadPage({ onNavigate }) {
  const [uploadedImages, setUploadedImages] = useState([]);
  const [previews, setPreviews] = useState([]);
  const [isWaitingGame, setIsWaitingGame] = useState(false); // 게임 준비 대기 상태
  const [waitingMessage, setWaitingMessage] = useState('');

  // 컴포넌트 마운트 상태 및 타임아웃 관리
  const isMounted = useRef(true);
  const timeoutRef = useRef(null);

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  // 이미지 파일 검증
  const validateImageFile = (file) => {
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    return allowedTypes.includes(file.type);
  };

  // 이미지 선택 핸들러
  const handleImageUpload = (e) => {
    const files = Array.from(e.target.files);

    if (uploadedImages.length + files.length > MAX_IMAGES) {
      alert(`최대 ${MAX_IMAGES}장까지만 업로드 가능합니다.`);
      return;
    }

    const validFiles = files.filter(validateImageFile);

    if (validFiles.length !== files.length) {
      alert('jpg, jpeg, png 파일만 업로드 가능합니다.');
    }

    if (validFiles.length === 0) return;

    // 미리보기 생성
    const newPreviews = [];
    for (const file of validFiles) {
      const reader = new FileReader();
      reader.onload = (event) => {
        newPreviews.push(event.target.result);
        if (newPreviews.length === validFiles.length) {
          setPreviews((prev) => [...prev, ...newPreviews]);
        }
      };
      reader.readAsDataURL(file);
    }

    setUploadedImages((prev) => [...prev, ...validFiles]);
  };

  // 슬롯 하나 업로드: 축소 → S3 PUT → 완료 알림(서버가 즉시 AI 파이프라인 시작)
  const uploadSlot = async (gameId, file, slot) => {
    const prepared = await prepareImageForUpload(file);
    const s3Response = await fetch(slot.presigned_url, {
      method: 'PUT',
      body: prepared,
      headers: { 'Content-Type': prepared.type },
    });
    if (!s3Response.ok) {
      throw new Error(`S3 업로드 실패 (slot ${slot.slot}, HTTP ${s3Response.status})`);
    }
    const completeResponse = await postJson(`/api/v1/games/${gameId}/uploads/complete`, {
      slot: slot.slot,
    });
    if (!completeResponse.ok) {
      throw new Error(`업로드 완료 알림 실패 (slot ${slot.slot}, HTTP ${completeResponse.status})`);
    }
    console.log(`슬롯 ${slot.slot} 업로드 완료 (${Math.round(prepared.size / 1024)} KB)`);
  };

  const reportUploadFailure = async (gameId, slotNumber) => {
    try {
      await postJson(`/api/v1/games/${gameId}/uploads/failed`, { slot: slotNumber });
    } catch (error) {
      console.warn('업로드 실패 보고 실패:', error);
    }
  };

  // 게임 시작 버튼 핸들러
  const handleStartGame = async () => {
    if (uploadedImages.length === 0) {
      alert('이미지를 먼저 업로드해주세요.');
      return;
    }

    try {
      setIsWaitingGame(true);
      setWaitingMessage('이미지를 업로드하고 있습니다…');

      // 1. 게임 생성 요청
      const gameResponse = await postJson('/api/v1/games', {
        mode: 'single',
        difficulty: 'easy',
        time_limit_seconds: 180,
        requested_slot_count: uploadedImages.length,
      });
      if (!gameResponse.ok) {
        alert('게임 생성 요청에 실패했습니다.');
        setIsWaitingGame(false);
        return;
      }

      const gameData = await gameResponse.json();
      const { game_id, upload_slots } = gameData;
      console.log('게임 생성 완료:', gameData);
      localStorage.setItem('currentGameRoomId', game_id.toString());

      // 2. 모든 이미지를 동시에 업로드. 각 슬롯은 업로드가 끝나는 즉시
      //    AI 파이프라인이 시작되므로 1번 이미지가 먼저 끝나면 바로 게임이 열린다.
      const results = await Promise.allSettled(
        uploadedImages.map((file, index) => uploadSlot(game_id, file, upload_slots[index]))
      );
      const failedSlots = results
        .map((result, index) => (result.status === 'rejected' ? upload_slots[index].slot : null))
        .filter((slot) => slot !== null);
      results.forEach((result) => {
        if (result.status === 'rejected') console.error(result.reason);
      });

      if (failedSlots.length === uploadedImages.length) {
        alert('이미지 업로드에 실패했습니다. 네트워크 상태를 확인하고 다시 시도해주세요.');
        setIsWaitingGame(false);
        return;
      }
      if (failedSlots.length > 0) {
        // 실패한 슬롯은 서버에 알려서 건너뛰게 한다 (나머지 이미지로 게임 진행).
        await Promise.all(failedSlots.map((slot) => reportUploadFailure(game_id, slot)));
        alert(`${failedSlots.length}장의 업로드에 실패해 해당 이미지는 건너뜁니다.`);
      }

      // 3. 첫 퍼즐이 준비될 때까지 상태 폴링
      const startedAt = Date.now();
      const totalRequested = uploadedImages.length - failedSlots.length;

      const scheduleNext = () => {
        if (isMounted.current) {
          timeoutRef.current = setTimeout(pollStatus, POLL_INTERVAL_MS);
        }
      };

      const pollStatus = async () => {
        if (!isMounted.current) return;

        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          alert('게임 생성 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.');
          setIsWaitingGame(false);
          return;
        }

        try {
          const statusResponse = await fetch(`/api/v1/games/${game_id}`);
          if (!isMounted.current) return;

          if (statusResponse.status === 404) {
            alert('게임 정보를 찾을 수 없습니다. 다시 시도해주세요.');
            setIsWaitingGame(false);
            return;
          }
          if (!statusResponse.ok) {
            console.error('상태 조회 실패, 재시도합니다:', statusResponse.status);
            scheduleNext();
            return;
          }

          const statusData = await statusResponse.json();
          console.log('게임 상태:', statusData);

          if (statusData.status === 'failed') {
            alert('AI가 이 사진에서 퍼즐을 만들 수 없었습니다. 다른 사진으로 시도해주세요.');
            setIsWaitingGame(false);
            return;
          }

          if (statusData.status === 'playing' && statusData.puzzle) {
            // 첫 스테이지 준비 완료. 남은 이미지는 플레이 중에 계속 생성된다.
            setIsWaitingGame(false);
            onNavigate('game');
            return;
          }

          const ready = statusData.ready_stages ?? 0;
          const total = statusData.total_stages ?? totalRequested;
          const failedNote =
            statusData.failed_stages > 0 ? ` (${statusData.failed_stages}장은 생성 실패로 건너뜀)` : '';
          setWaitingMessage(`AI가 퍼즐을 만들고 있습니다… ${ready}/${total} 완료${failedNote}`);
          scheduleNext();
        } catch (error) {
          console.error('폴링 중 에러, 재시도합니다:', error);
          scheduleNext();
        }
      };

      setWaitingMessage('AI가 퍼즐을 만들고 있습니다…');
      pollStatus();
    } catch (error) {
      console.error('게임 시작 에러:', error);
      if (isMounted.current) {
        alert('게임 시작 중 오류가 발생했습니다.');
        setIsWaitingGame(false);
      }
    }
  };

  // 뒤로가기 버튼 핸들러
  const handleGoBack = () => {
    setPreviews([]);
    setUploadedImages([]);
    onNavigate('home');
  };

  return (
    <div className="upload-page">
      {isWaitingGame && (
        <div className="waiting-overlay">
          <div className="waiting-content">
            <div className="spinner"></div>
            <h3>게임 준비 중...</h3>
            <p>{waitingMessage || 'AI가 퍼즐을 생성하고 있습니다. 잠시만 기다려주세요.'}</p>
            <p className="waiting-hint">첫 번째 퍼즐이 준비되면 바로 시작됩니다.</p>
          </div>
        </div>
      )}

      <div className="upload-content">
        <h2>이미지 업로드</h2>
        <p className="upload-info">최대 {MAX_IMAGES}장까지 업로드 가능 (jpg, jpeg, png)</p>

        <div
          className={`upload-area ${uploadedImages.length >= MAX_IMAGES ? 'disabled' : ''}`}
          onClick={() => {
            if (uploadedImages.length < MAX_IMAGES) {
              document.getElementById('image-input')?.click();
            }
          }}
        >
          <input
            type="file"
            id="image-input"
            multiple
            accept=".jpg,.jpeg,.png"
            onChange={handleImageUpload}
            style={{ display: 'none' }}
            disabled={uploadedImages.length >= MAX_IMAGES}
          />

          {previews.length === 0 ? (
            <div className="upload-empty-state">
              <div className="upload-icon">
                <svg width="100" height="100" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M7 18C4.23858 18 2 15.7614 2 13C2 10.2386 4.23858 8 7 8C7.33962 8 7.67482 8.02857 8.00289 8.08296C8.00329 8.05531 8.00362 8.02759 8.00388 8C8.00388 5.23858 10.2425 3 13.0039 3C15.7653 3 18.0039 5.23858 18.0039 8C18.0039 8.02759 18.0042 8.05531 18.0046 8.08296C18.3327 8.02857 18.6679 8 19.0075 8C21.769 8 24.0075 10.2386 24.0075 13C24.0075 15.7614 21.769 18 19.0075 18" stroke="#b0b0b0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  <path d="M12 11V17M9 14H15" stroke="#b0b0b0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <p className="upload-instruction">이미지를 드래그하거나 클릭하여 업로드하세요</p>
              <div className={`upload-label ${uploadedImages.length >= MAX_IMAGES ? 'disabled' : ''}`}>
                {uploadedImages.length >= MAX_IMAGES
                  ? '최대 업로드 개수 도달'
                  : '+ 이미지 업로드'}
              </div>
            </div>
          ) : (
            <div className="preview-container">
              {previews.map((preview, index) => (
                <div key={index} className="preview-item">
                  <img src={preview} alt={`미리보기 ${index + 1}`} />
                  <span className="preview-number">{index + 1}</span>
                </div>
              ))}
              {uploadedImages.length < MAX_IMAGES && (
                <div
                  className="upload-label-small"
                  onClick={(e) => {
                    e.stopPropagation();
                    document.getElementById('image-input')?.click();
                  }}
                >
                  + 추가 업로드
                </div>
              )}
            </div>
          )}
        </div>

        <div className="button-group">
          <button onClick={handleGoBack} className="back-button">
            뒤로가기
          </button>
          <button
            onClick={handleStartGame}
            className="start-button"
            disabled={uploadedImages.length === 0}
          >
            게임 시작
          </button>
        </div>
      </div>
    </div>
  );
}

export default ImageUploadPage;
