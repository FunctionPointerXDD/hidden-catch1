import React from 'react';
import './HomePage.css';

function HomePage({ onNavigate }) {
  const handlePlay = () => {
    onNavigate('upload');
  };

  const handleMultiplay = () => {
    // TODO: 멀티플레이 기능 (현재는 없음)
    console.log('멀티플레이 - 구현 예정');
  };

  return (
    <div className="home-page">
      <div className="home-content">
        <h2 className="home-subtitle">틀린그림찾기 게임</h2>
        <div className="button-container">
          <button onClick={handlePlay} className="game-button play-button">
            플레이
          </button>
          <button onClick={handleMultiplay} className="game-button multiplay-button" disabled>
            멀티플레이 (준비중)
          </button>
        </div>
      </div>
    </div>
  );
}

export default HomePage;
