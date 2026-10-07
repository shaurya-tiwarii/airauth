import { useState } from "react";
import { useAirDraw } from "../useAirDraw";
import { API, getAuth } from "../api";

/** One-time profile setup: 3 passes, auto-captured, then create the template. */
export default function Enroll({ go, refresh }) {
  const [passes, setPasses] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const draw = useAirDraw((s) => {
    setPasses((old) => old.length < 3 ? [...old, s] : old);
  });

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
      refresh();
      go("dashboard");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return (
    <main className="workspace">
      <div className="workspace-top">
        <button className="back-link" onClick={() => go("dashboard")}>← Back</button>
        <div>
          <div className="eyebrow">PROFILE SETUP</div>
          <h2>Enroll your signature once.</h2>
          <p>Draw three natural passes. After this, every document needs just one verification to sign.</p>
        </div>
      </div>
      <div className="workspace-grid">
        <section className="camera-card">
          <div className="camera-head">
            <span className={draw.cameraOn ? "green-dot" : "grey-dot"} />
            {draw.cameraOn ? "LIVE CAMERA" : "CAMERA OFF"} <span>{draw.status}</span>
          </div>
          <div className="camera-frame">
            <video ref={draw.videoRef} muted playsInline />
            <canvas ref={draw.canvasRef} width="1280" height="720" />
            {!draw.cameraOn && <div className="camera-empty"><b>◉</b><span>Enable your camera to begin.</span></div>}
            <div className="camera-guide">Pinch thumb + index to draw, release to capture</div>
          </div>
          <div className="camera-actions">
            <button className="light-auth-button" onClick={draw.clear}>Clear</button>
            {!draw.cameraOn
              ? <button className="dark-auth-button" onClick={draw.startCamera}>Enable camera</button>
              : passes.length === 3
                ? <button className="dark-auth-button" onClick={enroll} disabled={busy}>
                    {busy ? "Creating..." : "Create my signature profile"}
                  </button>
                : <button className="dark-auth-button" disabled>Pass {passes.length + 1} of 3: draw now</button>}
          </div>
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
          <button className="light-auth-button full" onClick={() => setPasses([])}>Start over</button>
          {error && <div className="error-card">⚠ {error}</div>}
          {draw.error && <div className="error-card">⚠ {draw.error}</div>}
        </aside>
      </div>
    </main>
  );
}
