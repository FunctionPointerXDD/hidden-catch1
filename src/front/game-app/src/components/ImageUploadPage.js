import React, { useState } from 'react';
import './ImageUploadPage.css';

function ImageUploadPage({ onNavigate, sessionId, uploadedImages, setUploadedImages, imageData, setImageData }) {
  const [previews, setPreviews] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const MAX_IMAGES = 5;

  // 테스트 모드로 게임 시작
  const handleTestMode = () => {
    // 테스트용 Mock 이미지 데이터
    const mockImageData = [
      {
        original: 'https://via.placeholder.com/800x600/FF6B6B/FFFFFF?text=Original+Image+1',
        modified: 'https://via.placeholder.com/800x600/4ECDC4/FFFFFF?text=Modified+Image+1'
      },
      {
        original: 'https://via.placeholder.com/800x600/95E1D3/000000?text=Original+Image+2',
        modified: 'https://via.placeholder.com/800x600/F38181/FFFFFF?text=Modified+Image+2'
      }
    ];

    setImageData(mockImageData);
    localStorage.setItem('currentGameRoomId', 'test_room_' + Date.now());
    
    // 약간의 지연 후 게임 페이지로 이동 (이미지 로드를 위해)
    setTimeout(() => {
      onNavigate('game');
    }, 100);
  };

  // 이미지 파일 검증
  const validateImageFile = (file) => {
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    return allowedTypes.includes(file.type);
  };

  // 이미지 업로드 핸들러
  const handleImageUpload = async (e) => {
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

    setIsLoading(true);

    // 미리보기 생성
    const newPreviews = [];
    for (const file of validFiles) {
      const reader = new FileReader();
      reader.onload = (e) => {
        newPreviews.push(e.target.result);
        if (newPreviews.length === validFiles.length) {
          setPreviews([...previews, ...newPreviews]);
        }
      };
      reader.readAsDataURL(file);
    }

    // 서버로 이미지 업로드
    try {
      const formData = new FormData();
      validFiles.forEach((file, index) => {
        formData.append('images', file);
      });
      formData.append('sessionId', sessionId);

      // TODO: 실제 서버 엔드포인트로 변경 필요
      const response = await fetch('/api/upload-images', {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const data = await response.json();
        // 서버로부터 받은 데이터: { images: [{original: url, modified: url}, ...] }
        setImageData(data.images);
        setUploadedImages([...uploadedImages, ...validFiles]);
        
        // 첫 번째 이미지 데이터 미리 로드
        if (data.images.length > 0) {
          preloadImage(data.images[0].original);
          preloadImage(data.images[0].modified);
        }
      } else {
        alert('이미지 업로드에 실패했습니다.');
      }
    } catch (error) {
      console.error('업로드 에러:', error);
      alert('이미지 업로드 중 오류가 발생했습니다.');
    } finally {
      setIsLoading(false);
    }
  };

  // 이미지 미리 로드
  const preloadImage = (url) => {
    const img = new Image();
    img.src = url;
  };

  // 게임 시작 버튼 핸들러
  const handleStartGame = async () => {
    if (!imageData || imageData.length < 1) {
      alert('이미지를 먼저 업로드해주세요.');
      return;
    }

    // 첫 번째 이미지 데이터가 로드되었는지 확인
    const firstImage = imageData[0];
    if (!firstImage.original || !firstImage.modified) {
      alert('이미지 로딩 중입니다. 잠시만 기다려주세요.');
      return;
    }

    // 서버로 게임 시작 정보 전송
    try {
      const gameRoomId = 'room_' + Date.now();
      const currentTime = new Date().toISOString();

      // TODO: 실제 서버 엔드포인트로 변경 필요
      const response = await fetch('/api/game-start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          gameRoomId: gameRoomId,
          userId: sessionId,
          startTime: currentTime,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log('게임 시작 응답:', data);
        // 게임방 ID를 localStorage에 저장하여 GamePage에서 사용
        localStorage.setItem('currentGameRoomId', gameRoomId);
        onNavigate('game');
      } else {
        alert('게임 시작 요청에 실패했습니다.');
      }
    } catch (error) {
      console.error('게임 시작 에러:', error);
      // 에러가 발생해도 일단 게임은 진행 (프로토타입이므로)
      localStorage.setItem('currentGameRoomId', 'room_' + Date.now());
      onNavigate('game');
    }
  };

  // 뒤로가기 버튼 핸들러
  const handleGoBack = () => {
    setPreviews([]);
    setUploadedImages([]);
    setImageData(null);
    onNavigate('home');
  };

  return (
    <div className="upload-page">
      <div className="upload-content">
        <h2>이미지 업로드</h2>
        <p className="upload-info">최대 {MAX_IMAGES}장까지 업로드 가능 (jpg, jpeg, png)</p>
        
        {/* 테스트 모드 버튼 - 개발 환경에서만 표시 */}
        {process.env.REACT_APP_TEST_MODE_ENABLED === 'true' && (
          <>
            <div className="test-mode-container">
              <button onClick={handleTestMode} className="test-mode-button">
                🧪 테스트 모드로 시작
              </button>
              <p className="test-mode-info">서버 없이 게임을 테스트할 수 있습니다</p>
            </div>

            <div className="divider">
              <span>또는</span>
            </div>
          </>
        )}
        
        <div className="upload-area">
          <input
            type="file"
            id="image-input"
            multiple
            accept=".jpg,.jpeg,.png"
            onChange={handleImageUpload}
            style={{ display: 'none' }}
            disabled={uploadedImages.length >= MAX_IMAGES}
          />
          
          <label 
            htmlFor="image-input" 
            className={`upload-label ${uploadedImages.length >= MAX_IMAGES ? 'disabled' : ''}`}
          >
            {uploadedImages.length >= MAX_IMAGES 
              ? '최대 업로드 개수 도달' 
              : '+ 이미지 업로드'}
          </label>

          {isLoading && <div className="loading">업로드 중...</div>}

          <div className="preview-container">
            {previews.map((preview, index) => (
              <div key={index} className="preview-item">
                <img src={preview} alt={`미리보기 ${index + 1}`} />
                <span className="preview-number">{index + 1}</span>
              </div>
            ))}
          </div>
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
