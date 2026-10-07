import { useState, useEffect } from "react";
import Home from "./views/Home";
import AuthView from "./views/Auth";
import VerifyPortal from "./views/Verify";
import Dashboard from "./views/Dashboard";
import Signing from "./views/Signing";
import Enroll from "./views/Enroll";
import { getAuth, setAuth, Auth } from "./api";

export default function App() {
  const [route, setRoute] = useState({ name: "home" });
  const [auth, setAuthState] = useState(getAuth());

  // Any API call that comes back 401 (expired or invalid session) signs the
  // user out and sends them to the login screen, instead of failing silently.
  useEffect(() => {
    const onExpired = () => { setAuthState(null); setRoute({ name: "login" }); };
    window.addEventListener("airauth:expired", onExpired);
    return () => window.removeEventListener("airauth:expired", onExpired);
  }, []);

  const go = (name, params = {}) => {
    window.scrollTo(0, 0);
    setRoute({ name, ...params });
  };

  const onAuth = (data) => {
    setAuthState(data);
    // Enrollment is optional now: the Draw tab signs without a camera.
    // Users can enroll their air signature any time from the dashboard.
    go("dashboard");
  };

  // Re-fetch the profile after enrollment so the enrolled flag is real,
  // not the stale value from login time.
  const refreshAuth = async () => {
    try {
      const user = await Auth.me();
      const next = { ...(getAuth() || {}), user };
      setAuth(next);
      setAuthState(next);
    } catch {}
  };

  const onLogout = () => {
    setAuthState(null);
    go("home");
  };

  if (route.name === "home") return <Home go={go} auth={auth} />;
  if (route.name === "login" || route.name === "register")
    return (
      <div className="app-shell">
        <SimpleNav go={go} auth={auth} />
        <AuthView mode={route.name} go={go} onAuth={onAuth} />
      </div>
    );
  if (route.name === "verify")
    return (
      <div className="app-shell">
        <SimpleNav go={go} auth={auth} />
        <VerifyPortal />
      </div>
    );
  if (route.name === "dashboard") {
    if (!auth) { setTimeout(() => go("login"), 0); return null; }
    return (
      <div className="app-shell workspace-shell">
        <SimpleNav go={go} auth={auth} />
        <Dashboard auth={auth} go={go} onLogout={onLogout} />
      </div>
    );
  }
  if (route.name === "enroll") {
    if (!auth) { setTimeout(() => go("login"), 0); return null; }
    return (
      <div className="app-shell workspace-shell">
        <SimpleNav go={go} auth={auth} />
        <Enroll go={go} refresh={refreshAuth} />
      </div>
    );
  }
  if (route.name === "sign") {
    if (!auth || !route.doc) { setTimeout(() => go("dashboard"), 0); return null; }
    return (
      <div className="app-shell workspace-shell">
        <SimpleNav go={go} auth={auth} />
        <Signing doc={route.doc} go={go} refresh={refreshAuth} auth={auth} />
      </div>
    );
  }
  return <Home go={go} auth={auth} />;
}

function SimpleNav({ go, auth }) {
  return (
    <header className="nav solid">
      <button className="brand" onClick={() => go("home")}>
        <span className="brand-mark">A</span>
        <span>AirAuth</span>
      </button>
      <nav className="nav-links">
        <button className="linklike" onClick={() => go("verify")}>Verify a document</button>
      </nav>
      {auth
        ? <button className="nav-user" onClick={() => go("dashboard")}><span className="green-dot" /> {auth.user.name}</button>
        : <button className="nav-user" onClick={() => go("login")}>Sign in</button>}
    </header>
  );
}
