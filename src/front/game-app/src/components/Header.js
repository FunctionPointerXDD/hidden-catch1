import React from 'react';
import './Header.css';

function Header() {
  const handleLogin = () => {
    // TODO: 로그인 기능 구현
    console.log('로그인 클릭');
  };

  const handleSignup = () => {
    // TODO: 가입 기능 구현
    console.log('가입 클릭');
  };

  const handleRank = () => {
    // TODO: 랭크 기능 구현
    console.log('랭크 클릭');
  };

  return (
    <header className="header">
      <div className="header-title">
        <h1>Hidden Catch</h1>
      </div>
      <nav className="header-nav">
        <button onClick={handleLogin} className="nav-button">로그인</button>
        <button onClick={handleSignup} className="nav-button">가입</button>
        <button onClick={handleRank} className="nav-button">랭크</button>
      </nav>
    </header>
  );
}

export default Header;
