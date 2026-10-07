const BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
export const API = `${BASE}/api/v1`;
export const AIRSIG = `${BASE}/api/v1/airsig`;

export function getAuth() {
  try { return JSON.parse(localStorage.getItem("airauth_auth") || "null"); }
  catch { return null; }
}
export function setAuth(a) {
  if (a) localStorage.setItem("airauth_auth", JSON.stringify(a));
  else localStorage.removeItem("airauth_auth");
}

function headers() {
  const a = getAuth();
  return a && a.token ? { Authorization: `Bearer ${a.token}` } : {};
}

async function parse(res) {
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    // Session expired or invalid: drop the stale token and tell the app to
    // send the user back to the login screen.
    setAuth(null);
    window.dispatchEvent(new Event("airauth:expired"));
  }
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

export async function api(method, path, body) {
  const h = { ...headers(), "Content-Type": "application/json" };
  const res = await fetch(API + path, { method, headers: h,
    body: body === undefined ? undefined : JSON.stringify(body) });
  return parse(res);
}

export async function apiForm(path, formData) {
  const res = await fetch(API + path, { method: "POST", headers: headers(), body: formData });
  return parse(res);
}

export async function download(path, filename) {
  const res = await fetch(API + path, { headers: headers() });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

export const Auth = {
  register: (d) => api("POST", "/auth/register", d),
  login: (d) => api("POST", "/auth/login", d),
  me: () => api("GET", "/auth/me"),
  changePassword: (current_password, new_password) =>
    api("POST", "/auth/change-password", { current_password, new_password }),
};

export const Docs = {
  list: () => api("GET", "/docs"),
  upload: (file) => { const f = new FormData(); f.append("file", file); return apiForm("/docs/upload", f); },
  download: (id, name) => download(`/docs/${id}/download`, name),
  assign: (id, user_id) => api("POST", `/docs/${id}/assign`, { user_id }),
  remove: (id) => api("DELETE", `/docs/${id}`),
};

export const Sign = {
  sign: (d) => api("POST", "/sign", d),
  mine: () => api("GET", "/sign/mine"),
  download: (code) => download(`/sign/${code}/download`, `signed-${code}.pdf`),
};

export const Biz = {
  mine: () => api("GET", "/business/mine"),
  removeEmployee: (user_id) => api("POST", "/business/employees/remove", { user_id }),
};

export const Admin = {
  overview: () => api("GET", "/admin/overview"),
  businesses: () => api("GET", "/admin/businesses"),
  users: () => api("GET", "/admin/users"),
  audit: (limit = 200) => api("GET", `/admin/audit?limit=${limit}`),
};

export const Verify = {
  lookup: (code) => fetch(`${API}/verify/${encodeURIComponent(code.trim())}`).then(parse),
  checkFile: (code, file) => {
    const f = new FormData(); f.append("file", file);
    return fetch(`${API}/verify/${encodeURIComponent(code.trim())}/check`, { method: "POST", body: f }).then(parse);
  },
};
