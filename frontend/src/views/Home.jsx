import { useEffect, useRef } from "react";

export default function Home({ go, auth }) {
  const videoRef = useRef(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = 0.7;
    }
  }, []);

  return (
    <div className="app-shell home-shell">
      <div className="sky-backdrop" aria-hidden="true">
        <div className="sky-day" />
        <video ref={videoRef} className="sky-video" autoPlay muted loop playsInline src="sky-bg.mp4" />
      </div>

      <header className="nav">
        <button className="brand" onClick={() => go("home")}>
          <span className="brand-mark">A</span>
          <span>AirAuth</span>
        </button>
        <nav className="nav-links">
          <a href="#how">How it works</a>
          <a href="#security">Security</a>
          <button className="linklike" onClick={() => go("verify")}>Verify a document</button>
        </nav>
        <div className="nav-right">
          {auth
            ? <button className="nav-user" onClick={() => go("dashboard")}><span className="green-dot" /> {auth.user.name}</button>
            : <button className="nav-user" onClick={() => go("login")}>Sign in</button>}
        </div>
      </header>

      <main className="home-main">
        <section className="hero-centered">
          <div className="eyebrow hero-eyebrow">AIR-SIGNATURE DOCUMENT SIGNING</div>
          <h1>Sign documents<br /><span>the way you move.</span></h1>
          <p>Businesses register, teams enroll one air signature each, and every document
          is sealed with a verifiable AirAuth stamp. Anyone can check the code.</p>
          <div className="hero-cta-row">
            <button className="pill-cta" onClick={() => go(auth ? "dashboard" : "register")}>
              {auth ? "Open dashboard" : "Get started"}
            </button>
            <button className="pill-ghost" onClick={() => go("verify")}>Verify a document</button>
          </div>
        </section>

        <div className="bottom-hint">Scroll to explore</div>

        <section className="home-section" id="how">
          <div><b>01</b><strong>Enroll once</strong><p>Draw three air passes. Your profile keeps one fused template.</p></div>
          <div><b>02</b><strong>Sign with one draw</strong><p>Upload a PDF, draw once. Match it and the document is stamped.</p></div>
          <div><b>03</b><strong>Verify anywhere</strong><p>Every signed PDF carries a unique code. The portal proves it.</p></div>
        </section>

        <section className="home-section story" id="security">
          <div className="eyebrow">TWO THINGS GET CHECKED</div>
          <h2>The shape of your gesture.<br /><span>The way you draw it.</span></h2>
        </section>

        <section className="home-section about" id="about">
          <div className="about-card"><div className="about-icon">⌁</div><div><div className="eyebrow">TAMPER-EVIDENT</div><h3>Sealed to the file</h3><p>Each code is bound to the document's fingerprint. Change one byte and verification fails.</p></div></div>
          <div className="about-card"><div className="about-icon">◎</div><div><div className="eyebrow">TEAMS</div><h3>Built for businesses</h3><p>Employer admins manage teams with invite codes. Employees sign from their own profiles.</p></div></div>
        </section>
      </main>

      <footer className="footer">
        <span>AirAuth © 2026</span>
        <span>Air-signature document signing</span>
      </footer>
    </div>
  );
}
