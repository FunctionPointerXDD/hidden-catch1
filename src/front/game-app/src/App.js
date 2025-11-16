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
  const [uploadedImages, setUploadedImages] = useState([]);
  const [imageData, setImageData] = useState(null); // 서버로부터 받은 이미지 URL 데이터

  // 세션ID 생성 및 localStorage 저장
  useEffect(() => {
    let storedSessionId = localStorage.getItem('sessionId');
    
    if (!storedSessionId) {
      // TODO: 실제로는 서버로부터 받아야 함
      const newSessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
      localStorage.setItem('sessionId', newSessionId);
      setSessionId(newSessionId);
    } else {
      setSessionId(storedSessionId);
    }
  }, []);

  return (
    <div className="App">
      <Header />
      
      <main className="main-content">
        {currentPage === 'home' && (
          <HomePage 
            onNavigate={setCurrentPage}
          />
        )}
        
        {currentPage === 'upload' && (
          <ImageUploadPage 
            onNavigate={setCurrentPage}
            sessionId={sessionId}
            uploadedImages={uploadedImages}
            setUploadedImages={setUploadedImages}
            imageData={imageData}
            setImageData={setImageData}
          />
        )}
        
        {currentPage === 'game' && (
          <GamePage 
            onNavigate={setCurrentPage}
            sessionId={sessionId}
            imageData={imageData}
            setImageData={setImageData}
          />
        )}
      </main>
    </div>
  );
}

export default App;
