import React, { useState, useEffect } from 'react';
import './App.css';

// 컴포넌트들
import Header from './components/Header';
import HomePage from './components/HomePage';
import ImageUploadPage from './components/ImageUploadPage';
import GamePage from './components/GamePage';

function App() {
  const [currentPage, setCurrentPage] = useState('home'); // 'home', 'upload', 'game'
  const [sessionId, setSessionId] = useState(null);

  // 세션ID 생성 및 localStorage 저장
  useEffect(() => {
    let storedSessionId = localStorage.getItem('sessionId');
    
    if (!storedSessionId) {
      // TODO: 실제로는 서버로부터 받아야 함
      const newSessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
      localStorage.setItem('sessionId', newSessionId);
      setSessionId(newSessionId);
    } else {
      setSessionId(storedSessionId);
    }
  }, []);

  return (
    <div className="App">
      <div className="background-animation">
        <div className="circle circle-1"></div>
        <div className="circle circle-2"></div>
        <div className="circle circle-3"></div>
        <div className="circle circle-4"></div>
        <div className="circle circle-5"></div>
      </div>
      <Header onNavigate={setCurrentPage} />
      
      <main className="main-content">
        {currentPage === 'home' && (
          <HomePage 
            onNavigate={setCurrentPage}
          />
        )}
        
        {currentPage === 'upload' && (
          <ImageUploadPage 
            onNavigate={setCurrentPage}
          />
        )}
        
        {currentPage === 'game' && (
          <GamePage 
            onNavigate={setCurrentPage}
            sessionId={sessionId}
          />
        )}
      </main>
    </div>
  );
}

export default App;
