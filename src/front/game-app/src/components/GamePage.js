import React, { useState, useEffect, useRef } from 'react';
import './GamePage.css';

function GamePage({ onNavigate, sessionId }) {
  const [gameData, setGameData] = useState(null);
  const [puzzleData, setPuzzleData] = useState(null);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [timeLeft, setTimeLeft] = useState(180); // 3분 = 180초
  const [correctAnswers, setCorrectAnswers] = useState([]); // found_differences 배열
  const [wrongAnswers, setWrongAnswers] = useState([]); // 오답 좌표 [{x, y}, ...]
  const [gameRoomId, setGameRoomId] = useState(null);
  const [isGameOver, setIsGameOver] = useState(false);
  const [userScore, setUserScore] = useState(0); // 스테이지 점수
  const [finalScore, setFinalScore] = useState(0); // 최종 점수
  const [isWaiting, setIsWaiting] = useState(false);
  const [lives, setLives] = useState(10); // 목숨
  const [currentStage, setCurrentStage] = useState(0); // 현재 스테이지 번호

  const originalImageRef = useRef(null);
  const modifiedImageRef = useRef(null);
  const timerRef = useRef(null);
  const stageStartTimeRef = useRef(null); // 스테이지 시작 시간

  // 게임 초기화
  useEffect(() => {
    // localStorage에서 게임방 ID 가져오기
    const storedGameRoomId = localStorage.getItem('currentGameRoomId');
    if (storedGameRoomId) {
      setGameRoomId(storedGameRoomId);
      loadGameData(storedGameRoomId);
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 게임 데이터 로드
  const loadGameData = async (gameId) => {
    try {
      const response = await fetch(`${process.env.REACT_APP_API_URL}/api/v1/games/${gameId}`);

      if (!response.ok) {
        alert('게임 데이터를 불러오지 못했습니다.');
        return;
      }

      const data = await response.json();
      console.log('게임 데이터 로드:', data);

      setGameData(data);
      setPuzzleData(data.puzzle);
      setCurrentStage(data.current_stage || 0);
      setUserScore(data.current_score || 0);

      // 스테이지 시작 시간 기록
      stageStartTimeRef.current = Date.now();

      // 타이머 시작
      startTimer();
    } catch (error) {
      console.error('게임 데이터 로드 에러:', error);
      alert('게임 데이터 로드 중 오류가 발생했습니다.');
    }
  };

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
  const handleTimeOut = async () => {
    clearInterval(timerRef.current);
    alert('시간 초과! 다음 게임으로 넘어갑니다.');

    // 시간 초과로 스테이지 완료 처리
    await handleStageComplete();
  };

  // 이미지 클릭 핸들러
  const handleImageClick = async (e) => {
    if (!puzzleData || !gameRoomId) return;

    const img = e.target;
    const rect = img.getBoundingClientRect();

    // 실제 이미지의 표시 크기 계산 (object-fit: contain 고려)
    const imgWidth = img.naturalWidth;
    const imgHeight = img.naturalHeight;
    const containerWidth = rect.width;
    const containerHeight = rect.height;

    // 이미지 비율과 컨테이너 비율 계산
    const imgRatio = imgWidth / imgHeight;
    const containerRatio = containerWidth / containerHeight;

    let displayWidth, displayHeight, offsetX, offsetY;

    if (imgRatio > containerRatio) {
      // 이미지가 더 넓음 - 좌우에 꽉 차고 상하에 여백
      displayWidth = containerWidth;
      displayHeight = containerWidth / imgRatio;
      offsetX = 0;
      offsetY = (containerHeight - displayHeight) / 2;
    } else {
      // 이미지가 더 높음 - 상하에 꽉 차고 좌우에 여백
      displayWidth = containerHeight * imgRatio;
      displayHeight = containerHeight;
      offsetX = (containerWidth - displayWidth) / 2;
      offsetY = 0;
    }

    // 클릭 위치가 실제 이미지 영역 내부인지 확인
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    if (clickX < offsetX || clickX > offsetX + displayWidth ||
      clickY < offsetY || clickY > offsetY + displayHeight) {
      console.log('이미지 영역 밖 클릭 무시');
      return;
    }

    // 실제 이미지 좌표로 변환
    const imageX = Math.round((clickX - offsetX) * (imgWidth / displayWidth));
    const imageY = Math.round((clickY - offsetY) * (imgHeight / displayHeight));

    console.log(`클릭 좌표: (${imageX}, ${imageY}), 이미지 크기: ${imgWidth}x${imgHeight}`);

    // 서버로 클릭 좌표 전송
    try {
      const response = await fetch(`${process.env.REACT_APP_API_URL}/api/v1/games/${gameRoomId}/stages/${currentStage}/check`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          x: imageX,
          y: imageY
        }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log('답안 체크 응답:', data);

        // 현재 점수 업데이트
        setUserScore(data.current_score);

        // found_differences로 정답 표시 업데이트
        setCorrectAnswers(data.found_differences || []);

        if (data.is_correct) {
          // 정답 처리
          if (!data.is_already_found) {
            console.log('새로운 정답 발견!');
          }

          // 모든 정답을 찾았는지 확인
          if (data.found_difference_count >= data.total_difference_count) {
            handleAllCorrect();
          }
        } else {
          // 오답 처리 - X표시 추가
          // 목숨 차감
          const newLives = lives - 1;
          setLives(newLives);

          // 목숨이 0이 되면 게임오버 또는 다음 이미지로
          if (newLives <= 0) {
            clearInterval(timerRef.current);
            alert('목숨을 모두 소진했습니다. 다음 게임으로 넘어갑니다.');

            // 목숨 소진으로 스테이지 완료 처리
            setTimeout(async () => {
              await handleStageComplete();
            }, 500);
            return;
          }
          const wrongCoord = { x: clickX, y: clickY };
          setWrongAnswers([...wrongAnswers, wrongCoord]);
          // 1초 후 X표시 제거
          setTimeout(() => {
            setWrongAnswers(prev => prev.filter(coord =>
              coord.x !== clickX || coord.y !== clickY
            ));
          }, 1000);
        }

        // 게임 상태 확인
        if (data.game_status === 'completed') {
          setIsGameOver(true);
          clearInterval(timerRef.current);
        }
      } else {
        console.error('답안 체크 실패:', response.status);
      }
    } catch (error) {
      console.error('답안 체크 에러:', error);
    }
  };

  // 모든 정답을 찾았을 때
  const handleAllCorrect = async () => {
    clearInterval(timerRef.current);
    await handleStageComplete();
  };

  // 스테이지 완료 처리 (공통 로직)
  const handleStageComplete = async () => {
    // 플레이 시간 계산 (밀리초)
    const playTimeMilliseconds = Date.now() - stageStartTimeRef.current;

    try {
      // 스테이지 완료 요청
      const response = await fetch(`${process.env.REACT_APP_API_URL}/api/v1/games/${gameRoomId}/stages/${currentStage}/complete`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          play_time_milliseconds: playTimeMilliseconds
        }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log('스테이지 완료 응답:', data);

        // 점수 업데이트
        setUserScore(data.current_score);

        // status가 "next_stage"면 polling 시작
        if (data.status === 'waiting_next_stage') {
          console.log('다음 퍼즐 준비 중... polling 시작');
          pollNextPuzzle();
        } else if (data.status === 'playing' && data.next_puzzle) {
          // 바로 playing 상태면 다음 퍼즐로 전환
          moveToNextStage(data);
        } else if (!data.next_puzzle) {
          // 더 이상 스테이지가 없으면 게임 종료
          alert('모든 게임을 완료했습니다!');
          endGame();
        }
      } else {
        console.error('스테이지 완료 요청 실패:', response.status);
        alert('스테이지 완료 처리에 실패했습니다.');
      }
    } catch (error) {
      console.error('스테이지 완료 에러:', error);
      alert('스테이지 완료 중 오류가 발생했습니다.');
    }
  };

  // 다음 퍼즐 준비 상태 polling
  const pollNextPuzzle = () => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`${process.env.REACT_APP_API_URL}/api/v1/games/${gameRoomId}/stages/${currentStage}/complete`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            play_time_milliseconds: 0  // polling이므로 시간은 0
          }),
        });

        if (response.ok) {
          const data = await response.json();
          console.log('Polling 응답:', data);

          // status가 "playing"으로 바뀌면 다음 스테이지로 전환
          if (data.status === 'playing' && data.next_puzzle) {
            clearInterval(pollInterval);
            console.log('다음 퍼즐 준비 완료! 전환 시작');
            moveToNextStage(data);
          } else if (!data.next_puzzle) {
            // 다음 퍼즐이 없으면 게임 종료
            clearInterval(pollInterval);
            alert('모든 게임을 완료했습니다!');
            endGame();
          }
          // status가 여전히 "next_stage"면 계속 polling
        } else {
          console.error('Polling 실패:', response.status);
        }
      } catch (error) {
        console.error('Polling 에러:', error);
      }
    }, 1000);  // 1초마다 polling
  };

  // 다음 스테이지로 전환
  const moveToNextStage = (data) => {
    // 다음 퍼즐 데이터로 업데이트
    setPuzzleData(data.next_puzzle);
    setCurrentStage(data.next_stage_number || currentStage);
    setGameData(prev => ({
      ...prev,
      current_stage: data.next_stage_number,
      total_stages: data.total_stages,
      current_score: data.current_score
    }));

    // 상태 초기화
    const nextIndex = currentImageIndex + 1;
    setCurrentImageIndex(nextIndex);
    setCorrectAnswers([]);
    setWrongAnswers([]);
    setLives(10);
    setTimeLeft(180);

    // 스테이지 시작 시간 기록
    stageStartTimeRef.current = Date.now();

    // 타이머 시작
    startTimer();
  };

  // 게임 종료
  const endGame = async () => {
    clearInterval(timerRef.current);

    try {
      // 게임 종료 요청
      const response = await fetch(`${process.env.REACT_APP_API_URL}/api/v1/games/${gameRoomId}/finish`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          play_time_milliseconds: 0
        }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log('게임 종료 응답:', data);

        // 최종 점수 저장
        setFinalScore(data.final_score);
        setIsGameOver(true);
      } else {
        console.error('게임 종료 요청 실패:', response.status);
        setIsGameOver(true);
      }
    } catch (error) {
      console.error('게임 종료 에러:', error);
      setIsGameOver(true);
    }
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

  if (!puzzleData) {
    return (
      <div className="game-page">
        <div className="error-message">이미지 데이터가 없습니다.</div>
      </div>
    );
  }

  // 게임 오버 화면
  if (isGameOver) {
    return (
      <div className="game-page">
        <div className="game-over">
          <h2>게임 종료!</h2>
          <p className="score">최종 점수: {finalScore}</p>
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
          <span>게임 {currentImageIndex + 1} / {gameData?.total_stages || 1}</span>
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
              src={puzzleData.original_image_url}
              alt="원본"
              onClick={(e) => handleImageClick(e, true)}
              className="game-image"
            />
            {/* 정답 표시 - rect 형태 */}
            {correctAnswers.map((diff, index) => (
              <div
                key={index}
                className="correct-mark"
                style={{
                  left: `${(diff.x / puzzleData.width) * 100}%`,
                  top: `${(diff.y / puzzleData.height) * 100}%`,
                  width: `${(diff.width / puzzleData.width) * 100}%`,
                  height: `${(diff.height / puzzleData.height) * 100}%`,
                }}
              />
            ))}
            {/* 오답 X표시 */}
            {wrongAnswers.map((coord, index) => (
              <div
                key={`wrong-${index}`}
                className="wrong-mark"
                style={{
                  left: `${(coord.x / puzzleData.width) * 100}%`,
                  top: `${(coord.y / puzzleData.height) * 100}%`,
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
              src={puzzleData.modified_image_url}
              alt="수정된 이미지"
              onClick={(e) => handleImageClick(e, false)}
              className="game-image"
            />
            {/* 정답 표시 - rect 형태 */}
            {correctAnswers.map((diff, index) => (
              <div
                key={index}
                className="correct-mark"
                style={{
                  left: `${(diff.x / puzzleData.width) * 100}%`,
                  top: `${(diff.y / puzzleData.height) * 100}%`,
                  width: `${(diff.width / puzzleData.width) * 100}%`,
                  height: `${(diff.height / puzzleData.height) * 100}%`,
                }}
              />
            ))}
            {/* 오답 X표시 */}
            {wrongAnswers.map((coord, index) => (
              <div
                key={`wrong-${index}`}
                className="wrong-mark"
                style={{
                  left: `${(coord.x / puzzleData.width) * 100}%`,
                  top: `${(coord.y / puzzleData.height) * 100}%`,
                }}
              >
                ✕
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="progress-info">
        <p>찾은 개수: {correctAnswers.length} / {puzzleData?.total_difference_count || 0}</p>
        <p>현재 점수: {userScore}</p>
      </div>

      <div className="game-footer">
        <button onClick={handleGoBack} className="back-button-game">
          돌아가기
        </button>
      </div>
    </div>
  );
}

export default GamePage;
