import { useState } from "react";
import { useAirDraw } from "../useAirDraw";
import { Sign } from "../api";

/**
 * Signing ceremony: one verification draw signs the document.
 * Stroke auto-captures when the pinch releases; verification runs on click.
 */
export default function Signing({ doc, go, refresh }) {
  const [includeVisible, setIncludeVisible] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stroke, setStroke] = useState(null);
  const [done, setDone] = useState(null);

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
      });
      setDone(res);
      refresh();
    } catch (err) {
      setError(err.message);
      setStroke(null);
    } finally { setBusy(false); }
  };

  if (done) {
    return (
      <main className="result-page">
        <div className="result-icon success">✓</div>
        <div className="eyebrow">DOCUMENT SIGNED</div>
        <h2>{doc.filename} is signed.</h2>
        <p>Verification code <b className="mono">{done.code}</b> is stamped on every page.</p>
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
          {stroke && <div className="pass-row done"><span>✓</span><div><b>Stroke captured</b><small>{stroke.points.length} points</small></div></div>}
          {error && <div className="error-card">⚠ {error}</div>}
          {draw.error && <div className="error-card">⚠ {draw.error}</div>}
        </aside>
      </div>
    </main>
  );
}
