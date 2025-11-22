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
      const response = await fetch(`/api/v1/games/${gameId}`);
      
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

    const rect = e.target.getBoundingClientRect();
    // 실제 픽셀 좌표 계산 (정규화하지 않음)
    const clickX = Math.round((e.clientX - rect.left) * (puzzleData.width / rect.width));
    const clickY = Math.round((e.clientY - rect.top) * (puzzleData.height / rect.height));

    console.log(`클릭 좌표: (${clickX}, ${clickY}), 이미지 크기: ${puzzleData.width}x${puzzleData.height}`);

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

    // 서버로 클릭 좌표 전송
    try {
      const response = await fetch(`/api/v1/games/${gameRoomId}/stages/${currentStage}/check`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          x: clickX,
          y: clickY
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
      const response = await fetch(`/api/v1/games/${gameRoomId}/stages/${currentStage}/complete`, {
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
        
        // 점수 및 상태 업데이트
        setUserScore(data.current_score);
        setCurrentStage(data.stage_number);
        
        setTimeout(() => {
          // next_puzzle이 있으면 다음 스테이지로
          if (data.next_puzzle) {
            // 다음 퍼즐 데이터로 업데이트
            setPuzzleData(data.next_puzzle);
            setGameData(prev => ({
              ...prev,
              current_stage: data.stage_number + 1,
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
          } else {
            // 더 이상 스테이지가 없으면 게임 종료
            alert('모든 게임을 완료했습니다!');
            endGame();
          }
        }, 1000);
      } else {
        console.error('스테이지 완료 요청 실패:', response.status);
        alert('스테이지 완료 처리에 실패했습니다.');
      }
    } catch (error) {
      console.error('스테이지 완료 에러:', error);
      alert('스테이지 완료 중 오류가 발생했습니다.');
    }
  };

  // 게임 종료
  const endGame = async () => {
    clearInterval(timerRef.current);
    
    try {
      // 게임 종료 요청
      const response = await fetch(`/api/v1/games/${gameRoomId}/finish`, {
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
