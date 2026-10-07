import { useState } from "react";
import { Verify } from "../api";

/** Public verification portal: no login needed. */
export default function VerifyPortal() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState(null);
  const [check, setCheck] = useState(null);

  const lookup = async (e) => {
    e.preventDefault();
    setError(""); setResult(null); setCheck(null); setBusy(true);
    try {
      setResult(await Verify.lookup(code));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const checkFile = async () => {
    if (!file || !result) return;
    setBusy(true); setCheck(null);
    try {
      setCheck(await Verify.checkFile(result.code, file));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return (
    <main className="auth-page">
      <div className="auth-card wide">
        <div className="eyebrow">PUBLIC VERIFICATION</div>
        <h2>Verify a signed document</h2>
        <p className="muted">
          Enter the verification code stamped on the document. To prove the file
          itself is unchanged since signing, upload it below and we will compare
          its fingerprint against the signed original.
        </p>
        <form onSubmit={lookup} className="row-form">
          <input value={code} onChange={(e) => setCode(e.target.value)}
            placeholder="AA-XXXXXXXX" className="code-input" />
          <button className="dark-auth-button" disabled={busy || !code.trim()}>
            {busy ? "..." : "Verify"}
          </button>
        </form>
        {error && <div className="error-card">{error}</div>}
        {result && (
          <div className="verify-result">
            <div className="verify-ok">Verified by AirAuth</div>
            <table className="kv">
              <tbody>
                <tr><td>Code</td><td><b>{result.code}</b></td></tr>
                <tr><td>Signed by</td><td>{result.signer_name}</td></tr>
                {result.business_name && <tr><td>Business</td><td>{result.business_name}</td></tr>}
                <tr><td>Document</td><td>{result.filename}</td></tr>
                <tr><td>Signed at</td><td>{new Date(result.signed_at).toLocaleString()}</td></tr>
                <tr><td>Document fingerprint</td><td className="mono">{result.doc_sha256.slice(0, 24)}...</td></tr>
              </tbody>
            </table>
            <div className="integrity">
              <b>Check file integrity</b>
              <p className="muted">Upload the document to confirm it is byte-for-byte
              the file that was signed.</p>
              <div className="row-form">
                <input type="file" accept="application/pdf"
                  onChange={(e) => setFile(e.target.files[0])} />
                <button className="light-auth-button" onClick={checkFile}
                  disabled={!file || busy}>Check file</button>
              </div>
              {check && (
                <div className={check.match ? "verify-ok" : "verify-bad"}>
                  {check.match
                    ? "This exact file was signed under this code."
                    : "This file differs from the signed original."}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
