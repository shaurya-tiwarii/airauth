import { useEffect, useRef, useState } from "react";
import { useAirDraw } from "../useAirDraw";
import { API, getAuth } from "../api";

const PASS_SECONDS = 10;

/** Draw pad for enrollment (mouse/finger), mirrors Signing.jsx DrawPad. */
function EnrollDrawPad({ onStroke }) {
  const ref = useRef(null);
  const drawing = useRef(false);
  const pts = useRef([]);
  const breaks = useRef(new Set());
  const [count, setCount] = useState(0);

  const paint = () => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    const p = pts.current;
    if (p.length < 2) return;
    ctx.beginPath();
    p.forEach((pt, i) => {
      const x = pt[0] * c.width, y = pt[1] * c.height;
      if (i === 0 || breaks.current.has(i)) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#14243a";
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();
  };

  const pos = (e) => {
    const c = ref.current, r = c.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    ];
  };

  const clear = () => {
    pts.current = [];
    breaks.current = new Set();
    drawing.current = false;
    setCount(0);
    onStroke(null);
    const c = ref.current;
    if (c) c.getContext("2d").clearRect(0, 0, c.width, c.height);
  };

  const capture = () => {
    if (pts.current.length >= 12) {
      onStroke({ points: [...pts.current], kinematics: [] });
    }
  };

  return (
    <>
      <div className="camera-frame draw-frame">
        <canvas
          ref={ref}
          width="1280"
          height="720"
          style={{ touchAction: "none", cursor: "crosshair" }}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            // New stroke after a lift: mark a break, don't connect.
            if (pts.current.length > 0) breaks.current.add(pts.current.length);
            drawing.current = true;
            pts.current.push(pos(e));
            setCount(pts.current.length);
            paint();
          }}
          onPointerMove={(e) => {
            if (!drawing.current) return;
            pts.current.push(pos(e));
            setCount(pts.current.length);
            paint();
          }}
          onPointerUp={() => { drawing.current = false; }}
          onPointerCancel={() => { drawing.current = false; }}
        />
        {count === 0 && (
          <div className="camera-empty draw-hint"><b>✎</b><span>Draw your signature here with mouse or finger.</span></div>
        )}
      </div>
      <div className="camera-actions">
        <button className="light-auth-button" onClick={clear}>Clear</button>
        <button className="dark-auth-button" onClick={capture} disabled={count < 12}>
          Capture this pass
        </button>
      </div>
    </>
  );
}

/** One-time profile setup: 3 passes with 10s timer each, then create the template. */
export default function Enroll({ go, refresh }) {
  const [mode, setMode] = useState("air"); // "air" | "draw"
  const [passes, setPasses] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(null);
  const timerRef = useRef(null);

  const addPass = (s) => {
    setPasses((old) => {
      if (old.length >= 3 || !s || s.points.length < 12) return old;
      return [...old, s];
    });
    stopTimer();
  };

  const draw = useAirDraw(addPass);

  const startTimer = () => {
    stopTimer();
    setSecondsLeft(PASS_SECONDS);
    timerRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        if (s === null) return null;
        if (s <= 1) {
          clearInterval(timerRef.current);
          timerRef.current = null;
          return 0;
        }
        return s - 1;
      });
    }, 1000);
  };

  const stopTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setSecondsLeft(null);
  };

  useEffect(() => () => stopTimer(), []);

  // When a pass is captured, the timer stops (handled in addPass).
  // Start the timer when the user begins a new pass.
  const beginPass = () => {
    if (passes.length < 3 && secondsLeft === null) startTimer();
  };

  const enroll = async () => {
    if (passes.length !== 3) return;
    setBusy(true); setError("");
    try {
      const a = getAuth();
      const res = await fetch(`${API}/auth/enroll`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${a.token}` },
        body: JSON.stringify({ user_id: "me", passes }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Enrollment failed.");
      await refresh();
      go("dashboard");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const switchMode = (m) => {
    setMode(m);
    setError("");
    stopTimer();
    if (m === "air") draw.clear();
  };

  const currentPass = passes.length + 1;

  return (
    <main className="workspace">
      <div className="workspace-top">
        <button className="back-link" onClick={() => go("dashboard")}>Back</button>
        <div>
          <div className="eyebrow">PROFILE SETUP</div>
          <h2>Enroll your signature once.</h2>
          <p>Three natural passes, 10 seconds each. After this, every document needs just one verification to sign.</p>
        </div>
      </div>
      <div className="sign-tabs">
        <button className={mode === "air" ? "active" : ""} onClick={() => switchMode("air")}>Air sign</button>
        <button className={mode === "draw" ? "active" : ""} onClick={() => switchMode("draw")}>Draw instead</button>
      </div>
      <div className="workspace-grid">
        <section className="camera-card">
          <div className="camera-head">
            <span className={mode === "air" && draw.cameraOn ? "green-dot" : "grey-dot"} />
            {mode === "air" ? (draw.cameraOn ? "LIVE CAMERA" : "CAMERA OFF") : "DRAW PAD"}
            <span>
              {secondsLeft !== null
                ? `${secondsLeft}s left in this pass`
                : mode === "air" ? draw.status : "Use mouse or finger"}
            </span>
          </div>
          {mode === "air" ? (
            <>
              <div className="camera-frame" onPointerDown={beginPass}>
                <video ref={draw.videoRef} muted playsInline />
                <canvas ref={draw.canvasRef} width="1280" height="720" />
                {!draw.cameraOn && <div className="camera-empty"><b>◉</b><span>Enable your camera to begin.</span></div>}
                <div className="camera-guide">Pinch thumb + index to draw, release to capture</div>
              </div>
              {secondsLeft !== null && (
                <div className="timer-bar"><span style={{ width: `${(secondsLeft / PASS_SECONDS) * 100}%` }} /></div>
              )}
              <div className="camera-actions">
                <button className="light-auth-button" onClick={() => { draw.clear(); stopTimer(); }}>Clear</button>
                {!draw.cameraOn
                  ? <button className="dark-auth-button" onClick={draw.startCamera}>Enable camera</button>
                  : passes.length === 3
                    ? <button className="dark-auth-button" onClick={enroll} disabled={busy}>
                        {busy ? "Creating..." : "Create my signature profile"}
                      </button>
                    : <button className="dark-auth-button" onClick={beginPass} disabled={secondsLeft !== null}>
                        {secondsLeft !== null ? `${secondsLeft}s...` : `Start pass ${currentPass} of 3 (10s)`}
                      </button>}
              </div>
            </>
          ) : (
            <>
              <div onPointerDown={beginPass}>
                <EnrollDrawPad onStroke={addPass} />
              </div>
              {secondsLeft !== null && (
                <div className="timer-bar"><span style={{ width: `${(secondsLeft / PASS_SECONDS) * 100}%` }} /></div>
              )}
              {passes.length === 3 && (
                <div className="camera-actions">
                  <button className="dark-auth-button" onClick={enroll} disabled={busy}>
                    {busy ? "Creating..." : "Create my signature profile"}
                  </button>
                </div>
              )}
            </>
          )}
        </section>
        <aside className="info-card">
          <div className="eyebrow">3-PASS ENROLLMENT</div>
          <h3>Draw naturally, three times.</h3>
          {[0, 1, 2].map((i) => (
            <div className={`pass-row ${passes.length > i ? "done" : passes.length === i ? "active" : ""}`} key={i}>
              <span>{passes.length > i ? "✓" : i + 1}</span>
              <div><b>Pass {i + 1}</b><small>{passes.length > i ? "Captured" : passes.length === i ? "Ready" : "Waiting"}</small></div>
            </div>
          ))}
          <div className="progress"><span style={{ width: `${(passes.length / 3) * 100}%` }} /></div>
          <button className="light-auth-button full" onClick={() => { setPasses([]); stopTimer(); }}>Start over</button>
          {error && <div className="error-card">⚠ {error}</div>}
          {draw.error && mode === "air" && <div className="error-card">⚠ {draw.error}</div>}
          <p className="muted small" style={{ marginTop: 12 }}>
            Each pass gives you 10 seconds. Lift your finger between strokes,
            gaps are fine and won't be connected.
          </p>
        </aside>
      </div>
    </main>
  );
}
