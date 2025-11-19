import React, { useState, useEffect, useRef } from 'react';
import './GamePage.css';

function GamePage({ onNavigate, sessionId, imageData, setImageData }) {
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [timeLeft, setTimeLeft] = useState(180); // 3분 = 180초
  const [correctAnswers, setCorrectAnswers] = useState([]); // [{x, y}, ...]
  const [wrongAnswers, setWrongAnswers] = useState([]); // 오답 좌표 [{x, y}, ...]
  const [gameRoomId, setGameRoomId] = useState(null);
  const [isGameOver, setIsGameOver] = useState(false);
  const [userScore, setUserScore] = useState(0);
  const [isWaiting, setIsWaiting] = useState(false);
  const [lives, setLives] = useState(10); // 목숨
  
  const originalImageRef = useRef(null);
  const modifiedImageRef = useRef(null);
  const timerRef = useRef(null);

  const TOTAL_DIFFERENCES = 3; // 틀린 부분 개수

  // 테스트 모드용 Mock 정답 좌표 (각 이미지마다 3개씩)
  const mockAnswers = [
    [
      { x: 0.25, y: 0.25 },
      { x: 0.5, y: 0.5 },
      { x: 0.75, y: 0.75 }
    ],
    [
      { x: 0.3, y: 0.4 },
      { x: 0.6, y: 0.6 },
      { x: 0.8, y: 0.3 }
    ]
  ];

  // 테스트 모드 클릭 핸들러 (목숨은 handleImageClick에서 이미 차감됨)
  const handleTestModeClick = (x, y) => {
    const currentMockAnswers = mockAnswers[currentImageIndex] || [];
    const tolerance = 0.1; // 10% 오차 허용

    // 클릭한 좌표가 정답 좌표 근처인지 확인
    const isCorrect = currentMockAnswers.some(answer => {
      const alreadyFound = correctAnswers.some(found => 
        Math.abs(found.x - answer.x) < 0.01 && Math.abs(found.y - answer.y) < 0.01
      );
      
      if (alreadyFound) return false;

      return Math.abs(x - answer.x) < tolerance && Math.abs(y - answer.y) < tolerance;
    });

    if (isCorrect) {
      // 정답을 찾은 경우
      const foundAnswer = currentMockAnswers.find(answer => 
        Math.abs(x - answer.x) < tolerance && Math.abs(y - answer.y) < tolerance
      );
      
      const newCorrectAnswers = [...correctAnswers, foundAnswer];
      setCorrectAnswers(newCorrectAnswers);

      console.log('정답! 현재 찾은 개수:', newCorrectAnswers.length);

      // 모든 정답을 찾았는지 확인
      if (newCorrectAnswers.length >= TOTAL_DIFFERENCES) {
        setTimeout(() => {
          if (currentImageIndex < imageData.length - 1) {
            // 다음 이미지로
            setCurrentImageIndex(currentImageIndex + 1);
            setCorrectAnswers([]);
            setWrongAnswers([]);
            setTimeLeft(180);
            setLives(10);
          } else {
            // 게임 종료
            setUserScore(newCorrectAnswers.length * 1000 + Math.floor(timeLeft * 10));
            setIsGameOver(true);
            clearInterval(timerRef.current);
          }
        }, 1000);
      }
    } else {
      console.log('오답입니다. 남은 목숨:', lives);
      // 오답 표시 추가
      const wrongCoord = { x, y };
      setWrongAnswers([...wrongAnswers, wrongCoord]);
      // 1초 후 X표시 제거
      setTimeout(() => {
        setWrongAnswers(prev => prev.filter(coord => coord.x !== x || coord.y !== y));
      }, 1000);
    }
  };

  // 게임 초기화
  useEffect(() => {
    // localStorage에서 게임방 ID 가져오기
    const storedGameRoomId = localStorage.getItem('currentGameRoomId');
    if (storedGameRoomId) {
      setGameRoomId(storedGameRoomId);
    } else {
      // 없으면 새로 생성 (fallback)
      const newGameRoomId = 'room_' + Date.now();
      setGameRoomId(newGameRoomId);
      localStorage.setItem('currentGameRoomId', newGameRoomId);
    }
    
    // 타이머 시작
    startTimer();

    // 다음 이미지 미리 로드
    if (imageData && imageData.length > 1) {
      preloadNextImages();
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentImageIndex]);

  // 타이머 시작
  const startTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }

    setTimeLeft(180);
    timerRef.current = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          handleTimeOut();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // 시간 초과 처리
  const handleTimeOut = () => {
    clearInterval(timerRef.current);
    alert('시간 초과! 다음 게임으로 넘어갑니다.');
    
    if (currentImageIndex < imageData.length - 1) {
      nextGame();
    } else {
      endGame();
    }
  };

  // 다음 이미지 미리 로드
  const preloadNextImages = () => {
    const nextIndex = currentImageIndex + 1;
    if (nextIndex < imageData.length) {
      const img1 = new Image();
      const img2 = new Image();
      img1.src = imageData[nextIndex].original;
      img2.src = imageData[nextIndex].modified;
    }
  };

  // 이미지 클릭 핸들러
  const handleImageClick = async (e, isOriginal) => {
    const rect = e.target.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width).toFixed(4);
    const y = ((e.clientY - rect.top) / rect.height).toFixed(4);
    const clickTime = new Date().toISOString();

    console.log(`클릭 좌표: (${x}, ${y}), 시각: ${clickTime}`);

    // 목숨 차감
    const newLives = lives - 1;
    setLives(newLives);

    // 목숨이 0이 되면 게임오버 또는 다음 이미지로
    if (newLives <= 0) {
      clearInterval(timerRef.current);
      
      if (currentImageIndex < imageData.length - 1) {
        // 다음 이미지가 존재하면 다음 게임으로
        alert('목숨을 모두 소진했습니다. 다음 게임으로 넘어갑니다.');
        setTimeout(() => {
          setCurrentImageIndex(currentImageIndex + 1);
          setCorrectAnswers([]);
          setWrongAnswers([]);
          setTimeLeft(180);
          setLives(10);
          startTimer();
        }, 500);
      } else {
        // 더 이상 이미지가 없으면 게임오버
        setIsGameOver(true);
        setUserScore(0);
        alert('목숨을 모두 소진했습니다. 게임오버!');
      }
      return;
    }

    // 테스트 모드 체크 (개발 환경에서만 활성화)
    const isTestMode = process.env.REACT_APP_TEST_MODE_ENABLED === 'true' && 
                       gameRoomId && gameRoomId.startsWith('test_');

    if (isTestMode) {
      // 테스트 모드: Mock 응답 생성 (이미 목숨은 차감됨)
      handleTestModeClick(parseFloat(x), parseFloat(y));
      return;
    }

    // 서버로 클릭 좌표 및 시각 전송
    try {
      const currentImage = imageData[currentImageIndex];
      
      // TODO: 실제 서버 엔드포인트로 변경 필요
      const response = await fetch('/api/check-answer', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          gameRoomId: gameRoomId,
          userId: sessionId,
          imageUrl: currentImage.original,
          x: parseFloat(x),
          y: parseFloat(y),
          clickTime: clickTime,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        // 서버 응답: { gameRoomId, userId, isCorrect, correctCoords: [{x, y}, ...], end: false, score: 0 }
        
        if (data.end) {
          // 게임 종료
          setUserScore(data.score);
          setIsGameOver(true);
          clearInterval(timerRef.current);
          return;
        }

        if (data.isCorrect) {
          // 정답 처리
          setCorrectAnswers(data.correctCoords);
          
          // 모든 정답을 찾았는지 확인
          if (data.correctCoords.length >= TOTAL_DIFFERENCES) {
            handleAllCorrect();
          }
        } else {
          // 오답 처리 - 이전 정답만 표시
          setCorrectAnswers(data.correctCoords);
          // 오답 X표시 추가
          const wrongCoord = { x: parseFloat(x), y: parseFloat(y) };
          setWrongAnswers([...wrongAnswers, wrongCoord]);
          // 1초 후 X표시 제거
          setTimeout(() => {
            setWrongAnswers(prev => prev.filter(coord => 
              coord.x !== parseFloat(x) || coord.y !== parseFloat(y)
            ));
          }, 1000);
        }
      }
    } catch (error) {
      console.error('답안 체크 에러:', error);
    }
  };

  // 모든 정답을 찾았을 때
  const handleAllCorrect = () => {
    clearInterval(timerRef.current);
    
    setTimeout(() => {
      if (currentImageIndex < imageData.length - 1) {
        nextGame();
      } else {
        alert('모든 게임을 완료했습니다!');
        endGame();
      }
    }, 1000);
  };

  // 다음 게임으로
  const nextGame = () => {
    const nextIndex = currentImageIndex + 1;
    
    // 다음 이미지가 로드되었는지 확인
    const nextImage = imageData[nextIndex];
    const img1 = new Image();
    const img2 = new Image();
    
    let loaded = 0;
    const checkLoaded = () => {
      loaded++;
      if (loaded === 2) {
        setIsWaiting(false);
        setCurrentImageIndex(nextIndex);
        setCorrectAnswers([]);
        setWrongAnswers([]);
        startTimer();
      }
    };

    setIsWaiting(true);
    img1.onload = checkLoaded;
    img2.onload = checkLoaded;
    img1.onerror = () => {
      alert('이미지 로딩 실패');
      setIsWaiting(false);
    };
    img2.onerror = () => {
      alert('이미지 로딩 실패');
      setIsWaiting(false);
    };
    
    img1.src = nextImage.original;
    img2.src = nextImage.modified;
  };

  // 게임 종료
  const endGame = () => {
    clearInterval(timerRef.current);
    
    // 10분 후 localStorage 정리 (600000ms)
    setTimeout(() => {
      localStorage.removeItem('uploadedImages');
      // TODO: 서버에 정리 요청 전송
      fetch('/api/cleanup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gameRoomId: gameRoomId,
          userId: sessionId,
          imageUrls: imageData.map(img => img.original),
        }),
      });
    }, 600000);
  };

  // 돌아가기
  const handleGoBack = () => {
    clearInterval(timerRef.current);
    setCurrentImageIndex(0);
    setCorrectAnswers([]);
    setWrongAnswers([]);
    setIsGameOver(false);
    onNavigate('home');
  };

  // 시간 포맷팅
  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  if (!imageData || imageData.length === 0) {
    return (
      <div className="game-page">
        <div className="error-message">이미지 데이터가 없습니다.</div>
      </div>
    );
  }

  const currentImage = imageData[currentImageIndex];

  // 게임 오버 화면
  if (isGameOver) {
    return (
      <div className="game-page">
        <div className="game-over">
          <h2>게임 종료!</h2>
          <p className="score">당신의 점수: {userScore}</p>
          <button onClick={handleGoBack} className="back-button-game">
            돌아가기
          </button>
        </div>
      </div>
    );
  }

  // 대기 화면
  if (isWaiting) {
    return (
      <div className="game-page">
        <div className="waiting">
          <h2>다음 게임 준비 중...</h2>
          <div className="spinner"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="game-page">
      <div className="game-header">
        <div className="game-info">
          <div className="lives-container">
            <span className="lives-label">❤️ {lives}</span>
          </div>
        </div>
        <div className="game-progress">
          <span>게임 {currentImageIndex + 1} / {imageData.length}</span>
        </div>
        <div className="timer">
          <span className={timeLeft <= 30 ? 'timer-warning' : ''}>
            ⏱ {formatTime(timeLeft)}
          </span>
        </div>
      </div>

      <div className="game-container">
        <div className="image-section">
          <h3>원본 이미지</h3>
          <div className="image-wrapper">
            <img
              ref={originalImageRef}
              src={currentImage.original}
              alt="원본"
              onClick={(e) => handleImageClick(e, true)}
              className="game-image"
            />
            {/* 정답 표시 - 원본 이미지에도 표시 */}
            {correctAnswers.map((coord, index) => (
              <div
                key={index}
                className="correct-mark"
                style={{
                  left: `${coord.x * 100}%`,
                  top: `${coord.y * 100}%`,
                }}
              />
            ))}
            {/* 오답 X표시 */}
            {wrongAnswers.map((coord, index) => (
              <div
                key={`wrong-${index}`}
                className="wrong-mark"
                style={{
                  left: `${coord.x * 100}%`,
                  top: `${coord.y * 100}%`,
                }}
              >
                ✕
              </div>
            ))}
          </div>
        </div>

        <div className="image-section">
          <h3>틀린그림 이미지</h3>
          <div className="image-wrapper">
            <img
              ref={modifiedImageRef}
              src={currentImage.modified}
              alt="수정된 이미지"
              onClick={(e) => handleImageClick(e, false)}
              className="game-image"
            />
            {/* 정답 표시 */}
            {correctAnswers.map((coord, index) => (
              <div
                key={index}
                className="correct-mark"
                style={{
                  left: `${coord.x * 100}%`,
                  top: `${coord.y * 100}%`,
                }}
              />
            ))}
            {/* 오답 X표시 */}
            {wrongAnswers.map((coord, index) => (
              <div
                key={`wrong-${index}`}
                className="wrong-mark"
                style={{
                  left: `${coord.x * 100}%`,
                  top: `${coord.y * 100}%`,
                }}
              >
                ✕
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="progress-info">
        <p>찾은 개수: {correctAnswers.length} / {TOTAL_DIFFERENCES}</p>
      </div>
    </div>
  );
}

export default GamePage;
