import { useEffect, useRef, useState } from "react";
import { Auth, Docs, Sign, Biz, Admin, setAuth } from "../api";

function useDocs(auth) {
  const [docs, setDocs] = useState([]);
  const [sigs, setSigs] = useState([]);
  const load = async () => {
    setDocs(await Docs.list());
    setSigs(await Sign.mine());
  };
  useEffect(() => { load().catch(() => {}); }, []);
  return { docs, sigs, load };
}

function DocTable({ docs, onSign, onDownload, onDelete, showSign }) {
  const [confirmId, setConfirmId] = useState(null);
  if (!docs.length) return <p className="muted">No documents yet.</p>;
  return (
    <table className="tbl">
      <thead><tr><th>Document</th><th>Status</th><th></th></tr></thead>
      <tbody>
        {docs.map((d) => (
          <tr key={d.id}>
            <td>{d.filename}<br /><small className="mono">{d.sha256.slice(0, 16)}...</small></td>
            <td><span className={`pill ${d.status}`}>{d.status}</span></td>
            <td className="actions">
              <button className="link" onClick={() => onDownload(d)}>Original</button>
              {showSign && d.status !== "signed" && (
                <button className="link strong" onClick={() => onSign(d)}>Sign</button>
              )}
              {onDelete && (confirmId === d.id ? (
                <span className="confirm-row">
                  <button className="link danger strong"
                    onClick={() => { setConfirmId(null); onDelete(d); }}>Confirm delete</button>
                  {" "}
                  <button className="link" onClick={() => setConfirmId(null)}>Cancel</button>
                </span>
              ) : (
                <button className="link danger" onClick={() => setConfirmId(d.id)}>Delete</button>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SigTable({ sigs }) {
  if (!sigs.length) return <p className="muted">Nothing signed yet.</p>;
  return (
    <table className="tbl">
      <thead><tr><th>Code</th><th>Document</th><th>Signer</th><th>Signed at</th><th></th></tr></thead>
      <tbody>
        {sigs.map((s) => (
          <tr key={s.id}>
            <td className="mono"><b>{s.code}</b></td>
            <td>{s.filename}</td>
            <td>{s.signer_name}{s.business_name ? <><br /><small>{s.business_name}</small></> : null}</td>
            <td><small>{new Date(s.created_at).toLocaleString()}</small></td>
            <td><button className="link" onClick={() => Sign.download(s.code)}>Signed PDF</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Upload({ onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  const up = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setBusy(true); setError("");
    try { await Docs.upload(file); onDone(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); e.target.value = ""; }
  };
  return (
    <div>
      <button type="button" className="upload-btn" disabled={busy}
        onClick={() => inputRef.current?.click()}>
        {busy ? "Uploading..." : "Upload PDF"}
      </button>
      <input ref={inputRef} type="file" accept="application/pdf"
        style={{ display: "none" }} onChange={up} />
      {error && <div className="error-card">{error}</div>}
    </div>
  );
}

function ChangePassword() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setMsg("");
    try {
      await Auth.changePassword(cur, next);
      setMsg("Password changed.");
      setCur(""); setNext("");
    } catch (e2) { setErr(e2.message); }
  };
  return (
    <form onSubmit={submit} className="pw-form">
      <h4>Change password</h4>
      <input type="password" placeholder="Current password" autoComplete="current-password"
        value={cur} onChange={(e) => setCur(e.target.value)} required />
      <input type="password" placeholder="New password (8+ characters)" autoComplete="new-password"
        value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} />
      <button className="dark-auth-button" type="submit">Change password</button>
      {msg && <p className="ok-line">{msg}</p>}
      {err && <div className="error-card">{err}</div>}
    </form>
  );
}

function ProfileCard({ auth, go, refresh }) {
  return (
    <section className="dash-card">
      <div className="eyebrow">MY PROFILE</div>
      <h3>{auth.user.name}</h3>
      <p className="muted">{auth.user.email} · {auth.user.role.replace("_", " ")}</p>
      {auth.user.airsig_enrolled
        ? <p className="ok-line">Signature profile enrolled. One air verification signs any document.</p>
        : <><p className="muted">No air signature enrolled yet. You can still sign with the Draw tab; enroll here to unlock air signing.</p>
            <button className="dark-auth-button" onClick={() => go("enroll")}>Enroll my air signature</button></>}
      <ChangePassword />
    </section>
  );
}

/* ---------------- role dashboards ---------------- */

function UserDash({ auth, go, refresh }) {
  const { docs, sigs, load } = useDocs(auth);
  const [signDoc, setSignDoc] = useState(null);
  const startSign = (d) => {
    setSignDoc(d); go("sign", { doc: d });
  };
  const del = async (d) => {
    await Docs.remove(d.id);
    load();
  };
  return (
    <>
      <ProfileCard auth={auth} go={go} refresh={refresh} />
      <section className="dash-card">
        <div className="dash-head"><h3>My documents</h3><Upload onDone={load} /></div>
        <DocTable docs={docs} showSign onSign={startSign} onDelete={del}
          onDownload={(d) => Docs.download(d.id, d.filename)} />
      </section>
      <section className="dash-card">
        <h3>Signed by me</h3>
        <SigTable sigs={sigs} />
      </section>
    </>
  );
}

function EmployeeDash(p) {
  return <UserDash {...p} />;
}

function EmployerDash({ auth, go, refresh }) {
  const { docs, sigs, load } = useDocs(auth);
  const [biz, setBiz] = useState(null);
  const [assignSel, setAssignSel] = useState({});
  const [confirmDel, setConfirmDel] = useState(null);
  useEffect(() => { Biz.mine().then(setBiz).catch(() => {}); }, []);
  const remove = async (uid) => {
    if (!confirm("Remove this employee?")) return;
    await Biz.removeEmployee(uid);
    setBiz(await Biz.mine());
  };
  const startSign = (d) => {
    go("sign", { doc: d });
  };
  const employees = (biz?.employees || []).filter((e) => e.role === "employee");
  const assign = async (docId) => {
    const uid = parseInt(assignSel[docId] || "", 10);
    if (!uid) return;
    await Docs.assign(docId, uid);
    setAssignSel((s) => ({ ...s, [docId]: "" }));
    load();
  };
  const del = async (d) => {
    setConfirmDel(null);
    await Docs.remove(d.id);
    load();
  };
  return (
    <>
      <ProfileCard auth={auth} go={go} refresh={refresh} />
      <section className="dash-card">
        <div className="eyebrow">MY BUSINESS</div>
        <h3>{biz?.business?.name || "..."}</h3>
        <p className="muted">Invite code: <b className="mono">{biz?.business?.invite_code}</b>.
          Share it so employees can join.</p>
        <h4>Team ({biz?.employees?.length || 0})</h4>
        <table className="tbl"><tbody>
          {(biz?.employees || []).map((e) => (
            <tr key={e.id}><td>{e.name}<br /><small>{e.email}</small></td>
              <td>{e.role.replace("_", " ")}</td>
              <td>{e.airsig_enrolled ? "Enrolled" : "Not enrolled"}</td>
              <td>{e.role === "employee" &&
                <button className="link danger" onClick={() => remove(e.id)}>Remove</button>}</td>
            </tr>
          ))}
        </tbody></table>
      </section>
      <section className="dash-card">
        <div className="dash-head"><h3>Business documents</h3><Upload onDone={load} /></div>
        {docs.length ? (
          <table className="tbl">
            <thead><tr><th>Document</th><th>Status</th><th>Assigned to</th><th></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.filename}<br /><small className="mono">{d.sha256.slice(0, 16)}...</small></td>
                  <td><span className={`pill ${d.status}`}>{d.status}</span></td>
                  <td>
                    {d.assignee_user_id
                      ? <small>{(employees.find((e) => e.id === d.assignee_user_id) || {}).name || "Employee"}</small>
                      : <span className="muted small">Unassigned</span>}
                  </td>
                  <td className="actions">
                    <button className="link" onClick={() => Docs.download(d.id, d.filename)}>Original</button>
                    {d.status !== "signed" && (
                      <button className="link strong" onClick={() => startSign(d)}>Sign</button>
                    )}
                    {confirmDel === d.id ? (
                      <span className="confirm-row">
                        <button className="link danger strong" onClick={() => del(d)}>Confirm delete</button>
                        {" "}
                        <button className="link" onClick={() => setConfirmDel(null)}>Cancel</button>
                      </span>
                    ) : (
                      <button className="link danger" onClick={() => setConfirmDel(d.id)}>Delete</button>
                    )}
                    {d.status !== "signed" && employees.length > 0 && (
                      <span className="assign-row">
                        <select value={assignSel[d.id] || ""}
                          onChange={(e) => setAssignSel((s) => ({ ...s, [d.id]: e.target.value }))}>
                          <option value="">Assign...</option>
                          {employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                        </select>
                        <button className="link" onClick={() => assign(d.id)}
                          disabled={!assignSel[d.id]}>Assign</button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">No documents yet.</p>}
        <p className="muted small">Employees only see documents assigned to them, plus their own uploads.</p>
      </section>
      <section className="dash-card">
        <h3>Signature log</h3>
        <SigTable sigs={sigs} />
      </section>
    </>
  );
}

function PlatformDash({ auth, go, refresh }) {
  const [ov, setOv] = useState(null);
  const [bizs, setBizs] = useState([]);
  const [users, setUsers] = useState([]);
  const [sigs, setSigs] = useState([]);
  const [audit, setAudit] = useState([]);
  useEffect(() => {
    (async () => {
      setOv(await Admin.overview());
      setBizs(await Admin.businesses());
      setUsers(await Admin.users());
      setSigs(await Sign.mine());
      setAudit(await Admin.audit());
    })().catch(() => {});
  }, []);
  return (
    <>
      <section className="dash-card">
        <div className="eyebrow">PLATFORM ADMIN</div>
        <h3>Overview</h3>
        <div className="stat-row">
          <div className="stat"><b>{ov?.businesses ?? "-"}</b><span>Businesses</span></div>
          <div className="stat"><b>{ov?.documents ?? "-"}</b><span>Documents</span></div>
          <div className="stat"><b>{ov?.signatures ?? "-"}</b><span>Signatures</span></div>
          {Object.entries(ov?.users_by_role || {}).map(([r, n]) => (
            <div className="stat" key={r}><b>{n}</b><span>{r.replace("_", " ")}s</span></div>
          ))}
        </div>
      </section>
      <section className="dash-card"><h3>Businesses</h3>
        <table className="tbl"><tbody>
          {bizs.map((b) => <tr key={b.id}><td>{b.name}</td>
            <td className="mono">{b.invite_code}</td>
            <td><small>{new Date(b.created_at).toLocaleDateString()}</small></td></tr>)}
        </tbody></table>
      </section>
      <section className="dash-card"><h3>Users</h3>
        <table className="tbl"><tbody>
          {users.map((u) => <tr key={u.id}><td>{u.name}<br /><small>{u.email}</small></td>
            <td>{u.role.replace("_", " ")}</td>
            <td>{u.airsig_enrolled ? "Enrolled" : "-"}</td></tr>)}
        </tbody></table>
      </section>
      <section className="dash-card"><h3>All signatures</h3><SigTable sigs={sigs} /></section>
      <section className="dash-card"><h3>Audit log</h3>
        {audit.length ? (
          <table className="tbl">
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id}>
                  <td><small>{new Date(a.created_at).toLocaleString()}</small></td>
                  <td><small>{a.actor_name || a.actor_email || (a.actor_user_id ? `#${a.actor_user_id}` : "system")}</small></td>
                  <td><small className="mono">{a.action}</small></td>
                  <td><small className="mono">{a.detail}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">No audit events yet.</p>}
      </section>
    </>
  );
}

export default function Dashboard({ auth, go, onLogout }) {
  const [me, setMe] = useState(auth);
  const refresh = async () => {
    try {
      const u = await Auth.me();
      const next = { ...getAuthSafe(), user: u };
      setAuth(next); setMe(next);
    } catch {}
  };
  const role = me.user.role;
  return (
    <main className="dash">
      <div className="dash-top">
        <div><div className="eyebrow">DASHBOARD</div>
          <h2>{role === "platform_admin" ? "Platform" : role === "employer_admin" ? "Business" : "My workspace"}</h2></div>
        <button className="light-auth-button" onClick={() => { setAuth(null); onLogout(); }}>Log out</button>
      </div>
      {role === "user" && <UserDash auth={me} go={go} refresh={refresh} />}
      {role === "employee" && <EmployeeDash auth={me} go={go} refresh={refresh} />}
      {role === "employer_admin" && <EmployerDash auth={me} go={go} refresh={refresh} />}
      {role === "platform_admin" && <PlatformDash auth={me} go={go} refresh={refresh} />}
    </main>
  );
}

function getAuthSafe() {
  try { return JSON.parse(localStorage.getItem("airauth_auth") || "{}"); }
  catch { return {}; }
}
