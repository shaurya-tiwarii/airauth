import { useState } from "react";
import { Auth, setAuth } from "../api";

export default function AuthView({ mode, go, onAuth }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [businessName, setBusinessName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const data = mode === "login"
        ? await Auth.login({ email, password })
        : await Auth.register({ name, email, password, role,
            business_name: businessName, invite_code: inviteCode });
      setAuth(data);
      onAuth(data);
    } catch (err) {
      setError(err.message);
    } finally { setBusy(false); }
  };

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <div className="eyebrow">{mode === "login" ? "WELCOME BACK" : "CREATE YOUR PROFILE"}</div>
        <h2>{mode === "login" ? "Log in" : "Sign up"}</h2>
        <p className="muted">
          {mode === "login"
            ? "Access your documents and signature profile."
            : "One profile, one enrolled signature. Then every document needs just a single verification to sign."}
        </p>
        {mode === "register" && (
          <>
            <label>Full name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
            <label>Account type
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="user">Individual</option>
                <option value="employee">Employee (join a business)</option>
                <option value="employer_admin">Business (register a business)</option>
              </select>
            </label>
            {role === "employer_admin" && (
              <label>Business name<input value={businessName}
                onChange={(e) => setBusinessName(e.target.value)} required
                placeholder="Acme Corp" /></label>
            )}
            {role === "employee" && (
              <label>Business invite code<input value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)} required
                placeholder="BIZ-XXXXXX" /></label>
            )}
          </>
        )}
        <label>Email<input type="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Password<input type="password" value={password}
          onChange={(e) => setPassword(e.target.value)} required minLength={8} /></label>
        {error && <div className="error-card">{error}</div>}
        <button className="dark-auth-button full" disabled={busy}>
          {busy ? "Please wait..." : mode === "login" ? "Log in" : "Create profile"}
        </button>
        <p className="muted center">
          {mode === "login" ? "No profile yet? " : "Already have a profile? "}
          <button type="button" className="link" onClick={() => go(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Sign up" : "Log in"}
          </button>
        </p>
      </form>
    </main>
  );
}
