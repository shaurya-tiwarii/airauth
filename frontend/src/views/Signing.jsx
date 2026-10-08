import { useRef, useState } from "react";
import { useAirDraw } from "../useAirDraw";
import { Sign } from "../api";

/**
 * Signing ceremony with two ways to sign:
 * - "Air sign": one biometric verification draw via camera + hand tracking.
 * - "Draw": mouse / finger fallback when the camera cannot be used.
 *   The signer is authenticated by login; no biometric claim is made,
 *   but the stamped code and hash still seal the document identically.
 */
function DrawPad({ onStroke }) {
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
            drawing.current = true;
            pts.current = [pos(e)];
            breaks.current = new Set();
            paint();
          }}
          onPointerMove={(e) => {
            if (!drawing.current) return;
            pts.current.push(pos(e));
            setCount(pts.current.length);
            paint();
          }}
          onPointerUp={() => {
            drawing.current = false;
            if (pts.current.length >= 12) {
              onStroke({ points: [...pts.current], kinematics: [] });
            }
          }}
          onPointerCancel={() => { drawing.current = false; }}
        />
        {count === 0 && (
          <div className="camera-empty draw-hint"><b>✎</b><span>Draw your signature here with mouse or finger.</span></div>
        )}
      </div>
      <div className="camera-actions">
        <button className="light-auth-button" onClick={clear}>Clear</button>
      </div>
    </>
  );
}

export default function Signing({ doc, go, refresh, auth }) {
  const [mode, setMode] = useState("air");
  const [includeVisible, setIncludeVisible] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stroke, setStroke] = useState(null);
  const [done, setDone] = useState(null);
  const enrolled = !!auth?.user?.airsig_enrolled;

  const draw = useAirDraw((s) => setStroke(s));

  const sign = async () => {
    if (!stroke) return;
    setBusy(true); setError("");
    try {
      const res = await Sign.sign({
        doc_id: doc.id,
        points: stroke.points,
        kinematics: stroke.kinematics,
        include_visible_signature: includeVisible,
        method: mode,
      });
      setDone(res);
      refresh();
    } catch (err) {
      setError(err.message);
      setStroke(null);
    } finally { setBusy(false); }
  };

  const switchMode = (m) => {
    setMode(m);
    setStroke(null);
    setError("");
    if (m === "air") draw.clear();
  };

  if (done) {
    return (
      <main className="result-page">
        <div className="result-icon success">✓</div>
        <div className="eyebrow">DOCUMENT SIGNED</div>
        <h2>{doc.filename} is signed.</h2>
        <p>Verification code <b className="mono">{done.code}</b> is stamped on every page.
          {done.method === "draw" && " Signed with the draw fallback (account-verified)."}</p>
        <div className="result-actions">
          <button className="dark-auth-button" onClick={() => Sign.download(done.code)}>Download signed PDF</button>
          <button className="light-auth-button" onClick={() => go("dashboard")}>Back to dashboard</button>
        </div>
      </main>
    );
  }

  return (
    <main className="workspace">
      <div className="workspace-top">
        <button className="back-link" onClick={() => go("dashboard")}>Back</button>
        <div>
          <div className="eyebrow">SIGN DOCUMENT</div>
          <h2>{doc.filename}</h2>
          <p>Draw your signature once. If it matches your enrolled profile, the document gets stamped.</p>
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
            <span>{mode === "air" ? draw.status : "Use mouse or finger"}</span>
          </div>
          {mode === "air" ? (
            !enrolled ? (
              <div className="camera-frame">
                <div className="camera-empty">
                  <b>◉</b>
                  <span>Air signing needs a signature profile.</span>
                  <button className="dark-auth-button" onClick={() => go("enroll")}
                    style={{ marginTop: 12 }}>Enroll my air signature</button>
                  <span className="muted small" style={{ marginTop: 8 }}>
                    No camera? Use the Draw tab instead, it works right now.
                  </span>
                </div>
              </div>
            ) : (
            <>
              <div className="camera-frame">
                <video ref={draw.videoRef} muted playsInline />
                <canvas ref={draw.canvasRef} width="1280" height="720" />
                {!draw.cameraOn && <div className="camera-empty"><b>◉</b><span>Enable your camera to begin.</span></div>}
                <div className="camera-guide">Pinch thumb + index to draw, release to capture</div>
              </div>
              <div className="camera-actions">
                <button className="light-auth-button" onClick={() => { draw.clear(); setStroke(null); }}>Clear</button>
                {!draw.cameraOn
                  ? <button className="dark-auth-button" onClick={draw.startCamera}>Enable camera</button>
                  : <button className="dark-auth-button" onClick={sign} disabled={!stroke || busy}>
                      {busy ? "Verifying..." : stroke ? "Verify and sign" : "Draw your signature first"}
                    </button>}
              </div>
              {draw.livePoints > 0 && !stroke && (
                <div className="stroke-meter"><span style={{ width: `${Math.min(100, draw.livePoints / 1.2)}%` }} /></div>
              )}
            </>
            )
          ) : (
            <>
              <DrawPad onStroke={setStroke} />
              <div className="camera-actions">
                <button className="dark-auth-button" onClick={sign} disabled={!stroke || busy}>
                  {busy ? "Signing..." : stroke ? "Sign document" : "Draw your signature first"}
                </button>
              </div>
            </>
          )}
        </section>
        <aside className="info-card">
          <div className="eyebrow">SIGNATURE OPTIONS</div>
          <h3>One verification, one stamp.</h3>
          <label className="check">
            <input type="checkbox" checked={includeVisible}
              onChange={(e) => setIncludeVisible(e.target.checked)} />
            <span>Show my drawn signature visibly on the document <small>(optional)</small></span>
          </label>
          <p className="muted small">
            The "Verified by AirAuth" seal and your unique verification code are
            always stamped, on every page. Anyone can check the code on the
            public verification page.
          </p>
          {mode === "draw" && (
            <p className="muted small">
              The draw fallback signs as your logged-in account. It skips the
              biometric check, so use it when the camera cannot work.
            </p>
          )}
          {stroke && <div className="pass-row done"><span>✓</span><div><b>Stroke captured</b><small>{stroke.points.length} points</small></div></div>}
          {error && <div className="error-card">⚠ {error}</div>}
          {draw.error && mode === "air" && <div className="error-card">⚠ {draw.error}</div>}
        </aside>
      </div>

      <section className="howto">
        <h3>How to get a perfect verification</h3>
        <ol>
          <li><b>Light your hand, not the lens.</b> Face a lamp or window. Avoid sitting with a bright window behind you.</li>
          <li><b>Frame the hand.</b> Hold it 30 to 50 cm from the camera with the whole hand visible against a plain background.</li>
          <li><b>Pinch decisively.</b> Press thumb and index fingertip firmly together to start drawing. The on-screen dot turns green while the pinch registers.</li>
          <li><b>One smooth motion.</b> Draw at a steady, natural speed. Enroll and sign at the same size and speed every time.</li>
          <li><b>Release and freeze.</b> Open your fingers and hold still until "Stroke captured" appears. Moving during the pause discards nothing, but stillness is fastest.</li>
          <li><b>Rejected?</b> Slow down slightly and match the size of your enrolled signature. Three consistent enrollments beat one perfect one.</li>
          <li><b>Camera trouble?</b> Switch to the Draw tab and sign with mouse or finger. It verifies your logged-in account instead of biometrics, and the stamped code checks the same way.</li>
        </ol>
      </section>
    </main>
  );
}
