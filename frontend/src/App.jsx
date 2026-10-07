import React, { useEffect, useRef, useState } from "react";

const API_BASE = `${import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000"}/api/v1/airsig`;

export default function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const handsRef = useRef(null);
  const cameraRef = useRef(null);
  const streamRef = useRef(null);
  const pointsRef = useRef([]);
  const kinRef = useRef([]);
  const drawingRef = useRef(false);

  const [userId, setUserId] = useState("shaurya_01");
  const [view, setView] = useState("home");
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState("verify");
  const [cameraOn, setCameraOn] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [passes, setPasses] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => () => stopCamera(), []);

  const openAuth = (mode) => {
    setAuthMode(mode);
    setAuthOpen(true);
    setError("");
  };

  const closeAuth = () => {
    setAuthOpen(false);
    setError("");
  };

  const clearSignature = () => {
    pointsRef.current = [];
    kinRef.current = [];
    drawingRef.current = false;
    const c = canvasRef.current;
    if (c) c.getContext("2d").clearRect(0, 0, c.width, c.height);
  };

  const draw = () => {
    const c = canvasRef.current;
    if (!c || pointsRef.current.length < 2) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.beginPath();
    pointsRef.current.forEach((p, i) => {
      const x = p[0] * c.width, y = p[1] * c.height;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#111";
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();
  };

  const onHandResults = (results) => {
    const lm = results.multiHandLandmarks?.[0];
    if (!lm) {
      drawingRef.current = false;
      return;
    }
    const thumb = lm[4], index = lm[8];
    const pinch = Math.hypot(thumb.x - index.x, thumb.y - index.y) < 0.075;
    if (pinch) {
      const now = performance.now();
      const p = [1 - index.x, index.y];
      if (!drawingRef.current) {
        drawingRef.current = true;
        setStatus("Drawing…");
      }
      pointsRef.current.push(p);
      if (pointsRef.current.length > 1) {
        const prev = pointsRef.current[pointsRef.current.length - 2];
        const tilt = Math.atan2(p[1] - prev[1], p[0] - prev[0]);
        kinRef.current.push([p[0], p[1], now, tilt]);
      }
      draw();
    } else if (drawingRef.current) {
      drawingRef.current = false;
      setStatus("Stroke captured");
    }
  };

  const startCamera = async () => {
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera access is not supported in this browser.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (!videoRef.current) return;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      setCameraOn(true);
      setStatus("Camera ready");

      if (!window.Hands || !window.Camera) {
        throw new Error("Hand tracking failed to load (CDN unreachable). Check your connection and reload.");
      }
      const hands = new window.Hands({
        locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
      });
      hands.setOptions({
        maxNumHands: 1,
        modelComplexity: 1,
        minDetectionConfidence: 0.65,
        minTrackingConfidence: 0.65,
      });
      hands.onResults(onHandResults);
      handsRef.current = hands;

      const camera = new window.Camera(videoRef.current, {
        onFrame: async () => {
          if (handsRef.current) {
            await handsRef.current.send({ image: videoRef.current });
          }
        },
        width: 1280,
        height: 720,
      });
      cameraRef.current = camera;
      camera.start();
    } catch (e) {
      setCameraOn(false);
      setStatus("Camera unavailable");
      setError(e.message || "Unable to access camera.");
    }
  };

  const stopCamera = () => {
    cameraRef.current?.stop?.();
    cameraRef.current = null;
    handsRef.current?.close?.();
    handsRef.current = null;
    streamRef.current?.getTracks?.().forEach((t) => t.stop());
    streamRef.current = null;
    setCameraOn(false);
  };

  const beginEnroll = async () => {
    closeAuth();
    setView("enroll");
    setPasses([]);
    setResult(null);
    clearSignature();
    if (!cameraOn) await startCamera();
  };

  const beginVerify = async () => {
    closeAuth();
    setView("verify");
    setResult(null);
    clearSignature();
    if (!cameraOn) await startCamera();
  };

  const capturePass = () => {
    if (pointsRef.current.length < 12) {
      setError("Draw a longer signature before capturing this pass.");
      return;
    }
    setPasses((old) => [...old, {
      points: [...pointsRef.current],
      kinematics: [...kinRef.current]
    }]);
    clearSignature();
    setError("");
    setStatus("Pass captured");
  };

  const enroll = async () => {
    if (passes.length !== 3) return;
    setError("");
    setStatus("Creating secure template…");
    try {
      const res = await fetch(`${API_BASE}/enroll-fused`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId.trim(), passes }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Enrollment failed.");
      setView("success");
      setStatus("Enrollment complete");
    } catch (e) {
      setError(`Backend unavailable: ${e.message}. Make sure the FastAPI server is running on 127.0.0.1:8000.`);
      setStatus("Enrollment failed");
    }
  };

  const verify = async () => {
    if (pointsRef.current.length < 12) {
      setError("Draw your signature first.");
      return;
    }
    setError("");
    setStatus("Verifying…");
    try {
      const res = await fetch(`${API_BASE}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId.trim(),
          points: [...pointsRef.current],
          kinematics: [...kinRef.current],
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Verification failed.");
      setResult(data);
      setView("result");
      setStatus(data.authenticated ? "Identity verified" : "Signature rejected");
    } catch (e) {
      setError(`Backend unavailable: ${e.message}. Make sure the FastAPI server is running on 127.0.0.1:8000.`);
      setStatus("Verification failed");
    }
  };

  const home = () => {
    stopCamera();
    clearSignature();
    setPasses([]);
    setResult(null);
    setError("");
    setView("home");
    setStatus("Ready");
  };

  const homePage = view === "home";

  return (
    <div className={`app-shell ${homePage ? "home-shell" : "workspace-shell"}`}>
      {homePage && (
        <div className="sky-backdrop" aria-hidden="true">
          <video autoPlay loop muted playsInline src="/foundable-sky.mp4" />
          <div className="sky-soften" />
          <div className="sky-center-cover" />
        </div>
      )}

      <header className="nav">
        <button className="brand" onClick={home}>
          <span className="brand-mark">A</span>
          <span>AirAuth</span>
        </button>
        <nav className="nav-links">
          <a href="#how">How it works</a>
          <a href="#security">Security</a>
          <a href="#about">About</a>
        </nav>
        <button className="nav-user" onClick={() => openAuth("verify")}>
          <span className="green-dot" /> {userId}
        </button>
      </header>

      {homePage && (
        <main className="home-main">
          <section className="hero-centered">
            <div className="eyebrow hero-eyebrow">AI-POWERED AIR-SIGNATURE AUTHENTICATION</div>
            <h1>Authenticate with<br /><span>the way you move.</span></h1>
            <p>Draw your signature in the air. AirAuth learns the shape, movement and timing of your gesture to verify your identity.</p>
            <button className="pill-cta" onClick={() => openAuth("verify")}>Enter AirAuth <span>→</span></button>
          </section>

          <div className="bottom-hint">Scroll to explore</div>

          <section className="home-section" id="how">
            <div><b>01</b><strong>Draw in the air</strong><p>Pinch thumb + index and create a natural gesture.</p></div>
            <div><b>02</b><strong>Teach it your gesture</strong><p>Three passes are fused into your personal template.</p></div>
            <div><b>03</b><strong>Verify securely</strong><p>Trajectory and behavior are checked together.</p></div>
          </section>

          <section className="home-section story" id="security">
            <div className="eyebrow">TWO THINGS GET CHECKED</div>
            <h2>The shape of your gesture.<br /><span>The way you draw it.</span></h2>
          </section>

          <section className="home-section about" id="about">
            <div className="about-card"><div className="about-icon">⌁</div><div><div className="eyebrow">PRIVACY FIRST</div><h3>Local biometric vault</h3><p>AirAuth stores the encrypted signature template in your local backend for this prototype.</p></div></div>
            <div className="about-card"><div className="about-icon">◎</div><div><div className="eyebrow">RESPONSIVE</div><h3>Works on small screens too</h3><p>The camera view and drawing canvas adapt to desktop and smaller screens.</p></div></div>
          </section>
        </main>
      )}

      {authOpen && (
        <div className="modal-backdrop" onMouseDown={closeAuth}>
          <div className="auth-modal" onMouseDown={(e) => e.stopPropagation()}>
            <div className="cloud-wrap"><img src="/cloud-mascot.png" alt="" /></div>
            <button className="modal-close" onClick={closeAuth}>×</button>
            <div className="auth-title">Sign in with AirAuth</div>
            <p className="auth-subtitle">Draw your signature in the air to prove it's you.</p>
            <div className="auth-user">
              <label>User ID</label>
              <input value={userId} onChange={(e) => setUserId(e.target.value)} />
            </div>
            <button className="dark-auth-button" onClick={beginVerify}>Verify my signature</button>
            <button className="light-auth-button" onClick={beginEnroll}>Create a new signature</button>
            <div className="auth-divider"><span /> <em>or</em> <span /></div>
            <small>Camera access is required for air-signature tracking.</small>
          </div>
        </div>
      )}

      {!homePage && view !== "success" && view !== "result" && (
        <main className="workspace">
          <div className="workspace-top">
            <button className="back-link" onClick={home}>← Back</button>
            <div><div className="eyebrow">{view === "enroll" ? "ENROLLMENT" : "VERIFICATION"}</div><h2>{view === "enroll" ? "Create your signature." : "Verify your identity."}</h2><p>{view === "enroll" ? "Capture three natural passes." : "Draw the same gesture you enrolled with."}</p></div>
            <div className="workspace-user">{userId}</div>
          </div>

          <div className="workspace-grid">
            <section className="camera-card">
              <div className="camera-head"><span className={cameraOn ? "green-dot" : "grey-dot"} /> {cameraOn ? "LIVE CAMERA" : "CAMERA OFF"} <span>{status}</span></div>
              <div className="camera-frame">
                <video ref={videoRef} muted playsInline />
                <canvas ref={canvasRef} width="1280" height="720" />
                {!cameraOn && <div className="camera-empty"><b>◉</b><span>Enable your camera to begin.</span></div>}
                <div className="camera-guide">Pinch thumb + index to draw</div>
              </div>
              <div className="camera-actions">
                <button className="light-auth-button" onClick={clearSignature}>Clear</button>
                {!cameraOn ? <button className="dark-auth-button" onClick={startCamera}>Enable camera</button> :
                  view === "enroll" ? <button className="dark-auth-button" onClick={capturePass}>Capture pass {Math.min(passes.length + 1, 3)} →</button> :
                  <button className="dark-auth-button" onClick={verify}>Verify signature →</button>}
              </div>
            </section>

            <aside className="info-card">
              <div className="eyebrow">{view === "enroll" ? "3-PASS ENROLLMENT" : "VERIFICATION"}</div>
              <h3>{view === "enroll" ? "Draw three passes to build your template." : "Draw your gesture once to verify."}</h3>
              {view === "enroll" ? (
                <>
                  {[0,1,2].map((i) => <div className={`pass-row ${passes.length > i ? "done" : passes.length === i ? "active" : ""}`} key={i}><span>{passes.length > i ? "✓" : i + 1}</span><div><b>Pass {i + 1}</b><small>{passes.length > i ? "Captured" : passes.length === i ? "Ready" : "Waiting"}</small></div></div>)}
                  <div className="progress"><span style={{width:`${(passes.length/3)*100}%`}} /></div>
                  {passes.length === 3 && <button className="dark-auth-button full" onClick={enroll}>Create secure template</button>}
                </>
              ) : (
                <>
                  <div className="metric"><span>Shape</span><b>Trajectory</b></div>
                  <div className="metric"><span>Behavior</span><b>Movement pattern</b></div>
                  <div className="metric"><span>Identity</span><b>{userId}</b></div>
                  <div className="tip">Keep the gesture natural and inside the guide for the best match.</div>
                </>
              )}
              {error && <div className="error-card">⚠ {error}</div>}
            </aside>
          </div>
        </main>
      )}

      {view === "success" && (
        <main className="result-page">
          <div className="result-icon success">✓</div>
          <div className="eyebrow">ENROLLMENT COMPLETE</div>
          <h2>Your AirAuth signature is ready.</h2>
          <p>Three passes were fused for <b>{userId}</b>.</p>
          <div className="result-actions"><button className="dark-auth-button" onClick={beginVerify}>Test verification →</button><button className="light-auth-button" onClick={home}>Return home</button></div>
        </main>
      )}

      {view === "result" && result && (
        <main className="result-page">
          <div className={`result-icon ${result.authenticated ? "success" : "fail"}`}>{result.authenticated ? "✓" : "×"}</div>
          <div className="eyebrow">{result.authenticated ? "ACCESS GRANTED" : "ACCESS DENIED"}</div>
          <h2>{result.authenticated ? "Identity verified." : "Signature not recognized."}</h2>
          <p>{result.authenticated ? `Welcome back, ${userId}.` : "Try again with your enrolled gesture."}</p>
          <div className="result-score"><span>Margin</span><b>{result.margin > 0 ? "+" : ""}{result.margin}</b></div>
          <div className="result-actions"><button className="dark-auth-button" onClick={beginVerify}>Try again</button><button className="light-auth-button" onClick={home}>Return home</button></div>
        </main>
      )}

      <footer className="footer">
        <span>AirAuth © 2026</span>
        <span>AI-powered air-signature authentication</span>
      </footer>
    </div>
  );
}
