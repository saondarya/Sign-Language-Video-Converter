import { useState, useEffect } from 'react';
import Login from './Login';
import Signup from './Signup';

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:5031';

export default function App() {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [showSignup, setShowSignup] = useState(false);
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState('');
  const [transcript, setTranscript] = useState('');
  const [videoUrl, setVideoUrl] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [videoHistory, setVideoHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);

  // Check for existing session on mount
  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    const savedUser = localStorage.getItem('user');
    
    if (savedToken && savedUser) {
      try {
        const userData = JSON.parse(savedUser);
        if (userData && userData.id) {
          setToken(savedToken);
          setUser(userData);
          loadVideoHistory(savedToken);
        } else {
          // Invalid user data, clear it
          localStorage.removeItem('token');
          localStorage.removeItem('user');
        }
      } catch (error) {
        console.error('Failed to parse saved user data:', error);
        // Clear invalid data
        localStorage.removeItem('token');
        localStorage.removeItem('user');
      }
    }
  }, []);

  const loadVideoHistory = async (authToken) => {
    try {
      const response = await fetch(`${API_BASE}/videos`, {
        headers: {
          'Authorization': `Bearer ${authToken}`,
        },
      });
      
      if (response.ok) {
        let data;
        try {
          const text = await response.text();
          data = text ? JSON.parse(text) : {};
        } catch (parseError) {
          console.error('Failed to parse video history:', parseError);
          return;
        }
        setVideoHistory(data.videos || []);
      }
    } catch (error) {
      console.error('Failed to load video history:', error);
    }
  };

  const handleLogin = (userData, authToken) => {
    setUser(userData);
    setToken(authToken);
    setShowSignup(false);
    loadVideoHistory(authToken);
  };

  const handleSignup = (userData, authToken) => {
    setUser(userData);
    setToken(authToken);
    setShowSignup(false);
    loadVideoHistory(authToken);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setUser(null);
    setToken(null);
    setVideoHistory([]);
    setVideoUrl('');
    setTranscript('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!file) {
      setStatus('Please choose a video file first.');
      return;
    }

    if (!token) {
      setStatus('Please login first.');
      return;
    }

    setIsProcessing(true);
    setStatus('Uploading video and running transcription...');
    setTranscript('');
    setVideoUrl('');

    try {
      const formData = new FormData();
      formData.append('video', file);

      const response = await fetch(`${API_BASE}/process`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        if (response.status === 401) {
          handleLogout();
          throw new Error('Session expired. Please login again.');
        }
        throw new Error(error.error || 'Request failed');
      }

      const data = await response.json();
      setTranscript(data.transcript);
      // data.videoUrl is like "/output/{jobId}", prepend API_BASE
      setVideoUrl(`${API_BASE}${data.videoUrl}?t=${Date.now()}`);
      setStatus('Done! Scroll down to review the transcript and ASL video.');
      
      // Reload video history
      loadVideoHistory(token);
    } catch (error) {
      console.error(error);
      setStatus(error.message || 'Something went wrong.');
    } finally {
      setIsProcessing(false);
    }
  };

  // Show login/signup if not authenticated
  if (!user || !token) {
    return (
      <main className="app">
        <header>
          <h1>ASL Avatar Generator</h1>
          <p>Please login or sign up to continue.</p>
        </header>
        {showSignup ? (
          <Signup onSignup={handleSignup} onSwitchToLogin={() => setShowSignup(false)} />
        ) : (
          <Login onLogin={handleLogin} onSwitchToSignup={() => setShowSignup(true)} />
        )}
      </main>
    );
  }

  return (
    <main className="app">
      <header>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>ASL Avatar Generator</h1>
            <p>Welcome, {user.username}! Upload a short video to generate ASL translation.</p>
          </div>
          <button onClick={handleLogout} className="logout-button">
            Logout
          </button>
        </div>
      </header>

      <section className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 style={{ margin: 0 }}>New Translation</h2>
          <button 
            type="button" 
            onClick={() => {
              setShowHistory(!showHistory);
              if (!showHistory) {
                loadVideoHistory(token);
              }
            }}
            className="history-button"
          >
            {showHistory ? 'Hide' : 'Show'} Video History
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <label className="file-input">
            <span>Video file (.mp4 recommended)</span>
            <input
              type="file"
              accept="video/*"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={!file || isProcessing}>
            {isProcessing ? 'Processing…' : 'Generate ASL Video'}
          </button>
        </form>
        {status && <p className="status">{status}</p>}
      </section>

      {showHistory && videoHistory.length > 0 && (
        <section className="card">
          <h2>Your Video History</h2>
          <div className="video-history">
            {videoHistory.map((video) => {
              // video.videoUrl is like "/output/{jobId}"
              // For new tab, use absolute URL pointing directly to backend
              const videoUrl = `${BACKEND_URL}${API_BASE}${video.videoUrl}`;
              return (
                <div key={video.id} className="history-item">
                  <p className="history-transcript">{video.transcript}</p>
                  <div className="history-actions">
                    <a href={`${videoUrl}?t=${Date.now()}`} target="_blank" rel="noopener noreferrer">
                      View Video
                    </a>
                    {video.createdAt && (
                      <span className="history-date">
                        {new Date(video.createdAt).toLocaleString()}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {transcript && (
        <section className="card">
          <h2>Transcript</h2>
          <p className="transcript">{transcript}</p>
        </section>
      )}

      {videoUrl && (
        <section className="card">
          <h2>Generated ASL Video</h2>
          <video src={videoUrl} controls playsInline />
          <a className="download" href={videoUrl} download="signed_output.mp4">
            Download video
          </a>
        </section>
      )}
    </main>
  );
}

