/*
 * Shared building blocks for every dashboard.
 *
 * - api(): every call to the backend, with the login token attached
 * - formatting helpers (dates are always shown in Pakistan time)
 * - small UI pieces reused by the student, staff and admin screens
 * - the sign-in page, the page header and the notification bell
 *
 * This file is loaded first, so everything declared here is available to
 * the other dashboard files.
 */
const { useState, useEffect, useRef, useCallback } = React;

const TOKEN_KEY = "sqr_token";

const STATUS_STYLES = {
  "Pending": "bg-amber-50 text-amber-700 border-amber-200",
  "In Progress": "bg-blue-50 text-blue-700 border-blue-200",
  "Needs More Info": "bg-violet-50 text-violet-700 border-violet-200",
  "Escalated": "bg-red-50 text-red-700 border-red-200",
  "Resolved": "bg-emerald-50 text-emerald-700 border-emerald-200",
};
const STATUSES = Object.keys(STATUS_STYLES);

const INPUT_CLASS =
  "w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-sm text-slate-800 " +
  "focus:outline-none focus:border-slate-900";
const LABEL_CLASS = "text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5";


// --- Talking to the API ------------------------------------------------------

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function saveToken(token) { localStorage.setItem(TOKEN_KEY, token); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

function readError(data, status) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((item) => String(item.msg || "").replace(/^Value error, /, "")).join(" ");
  }
  return `Something went wrong (HTTP ${status}).`;
}

async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && token) {
    clearToken();
    window.dispatchEvent(new Event("session-expired"));
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(readError(data, response.status));
  }
  if (raw) return response;
  return response.status === 204 ? null : response.json();
}

async function downloadFile(path, fallbackName) {
  const response = await api(path, { raw: true });
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = match ? match[1] : fallbackName;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Loads `path` when the component appears; `reload()` fetches it again.
function useApi(path) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api(path));
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload };
}


// --- Formatting --------------------------------------------------------------

const PAKISTAN_TIME = { timeZone: "Asia/Karachi" };

function formatDateTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("en-GB", {
    ...PAKISTAN_TIME, day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function formatDate(value) {
  if (!value) return "";
  return new Date(value).toLocaleDateString("en-GB", { ...PAKISTAN_TIME, day: "2-digit", month: "short", year: "numeric" });
}

function timeAgo(value) {
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDate(value);
}


// --- UI pieces ---------------------------------------------------------------

const BUTTON_STYLES = {
  primary: "bg-slate-900 text-white hover:bg-slate-800",
  secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50",
  danger: "bg-white text-red-600 border border-red-200 hover:bg-red-50",
  warning: "bg-amber-600 text-white hover:bg-amber-700",
};

function Button({ variant = "primary", type = "button", className = "", ...props }) {
  return (
    <button
      type={type}
      className={`px-3.5 py-2 rounded-lg text-xs font-medium transition disabled:opacity-50 ` +
                 `disabled:cursor-not-allowed ${BUTTON_STYLES[variant]} ${className}`}
      {...props}
    />
  );
}

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style}`}>
      {status}
    </span>
  );
}

function CategoryPill({ category }) {
  return (
    <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
      {category || "Unclassified"}
    </span>
  );
}

function Card({ title, subtitle, actions, children, className = "", bodyClassName = "p-5" }) {
  return (
    <section className={`bg-white border border-slate-200 rounded-xl shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="px-5 py-4 border-b border-slate-200 flex items-center justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
            {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

function Alert({ type = "error", children, onClose }) {
  if (!children) return null;
  const styles = {
    error: "bg-red-50 border-red-200 text-red-700",
    success: "bg-emerald-50 border-emerald-200 text-emerald-800",
    info: "bg-blue-50 border-blue-200 text-blue-800",
  };
  return (
    <div className={`p-3 rounded-lg border text-xs flex items-start justify-between gap-3 ${styles[type]}`}>
      <span>{children}</span>
      {onClose && <button onClick={onClose} className="opacity-60 hover:opacity-100">✕</button>}
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-slate-700 mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-slate-400 mt-1">{hint}</span>}
    </label>
  );
}

function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className={`bg-white rounded-xl shadow-xl w-full ${wide ? "max-w-3xl" : "max-w-lg"} max-h-[90vh] overflow-y-auto`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-sm">✕</button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function Loading({ text = "Loading..." }) {
  return <p className="text-xs text-slate-400 py-8 text-center">{text}</p>;
}

function EmptyState({ children }) {
  return <p className="text-xs text-slate-400 py-10 text-center">{children}</p>;
}


function Logo() {
  return (
    <div className="w-8 h-8 rounded-lg bg-slate-900 text-white font-bold text-xs flex items-center justify-center">
      VU
    </div>
  );
}


// --- Query details (shared by students and staff) ----------------------------

function QueryTimeline({ history }) {
  return (
    <ol className="space-y-3">
      {history.map((entry, index) => (
        <li key={index} className="flex gap-3">
          <span className="mt-1.5 w-2 h-2 rounded-full bg-slate-400 flex-shrink-0" />
          <div className="text-xs">
            <div className="flex items-center gap-2 flex-wrap">
              <StatusBadge status={entry.new_status} />
              <span className="text-slate-500">{entry.changed_by} · {formatDateTime(entry.changed_at)}</span>
            </div>
            {entry.note && <p className="mt-1 text-slate-600 whitespace-pre-line">{entry.note}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function QueryOverview({ query }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <CategoryPill category={query.category} />
        <StatusBadge status={query.status} />
        <span>{query.department_name || "Awaiting manual review"}</span>
        {query.course_code && <span>· {query.course_code}</span>}
        <span>· via {query.channel}</span>
        <span>· {formatDateTime(query.created_at)}</span>
      </div>

      <div>
        <h4 className={LABEL_CLASS}>Query</h4>
        <p className="text-sm text-slate-800 whitespace-pre-line bg-slate-50 border border-slate-200 rounded-lg p-3 leading-relaxed">
          {query.query_text}
        </p>
      </div>

      {query.replies.length > 0 && (
        <div>
          <h4 className={LABEL_CLASS}>Official reply</h4>
          <div className="space-y-3">
            {query.replies.map((reply, index) => (
              <div key={index} className="bg-emerald-50 border border-emerald-200 rounded-lg p-3">
                <p className="text-sm text-slate-800 whitespace-pre-line leading-relaxed">{reply.text}</p>
                <p className="text-[11px] text-slate-500 mt-2">{reply.sent_by} · {formatDateTime(reply.sent_at)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <h4 className={LABEL_CLASS}>Timeline</h4>
        <QueryTimeline history={query.history} />
      </div>
    </div>
  );
}


// --- Sign-in page ------------------------------------------------------------

function LoginView({ onLogin }) {
  const buttonRef = useRef(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleCredential(response) {
    setBusy(true);
    setError("");
    try {
      const result = await api("/auth/google", { method: "POST", body: { credential: response.credential } });
      saveToken(result.access_token);
      onLogin(result.user);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    api("/auth/config")
      .then(({ google_client_id }) => {
        const showButton = () => {
          if (cancelled) return;
          if (!window.google || !window.google.accounts) return setTimeout(showButton, 200);
          window.google.accounts.id.initialize({ client_id: google_client_id, callback: handleCredential });
          window.google.accounts.id.renderButton(buttonRef.current, {
            theme: "outline", size: "large", width: 300, text: "continue_with",
          });
        };
        showButton();
      })
      .catch((err) => setError(err.message));
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center gap-3">
        <Logo />
        <span className="text-sm font-semibold">Virtual University of Pakistan</span>
      </header>

      <main className="flex-1 flex items-center justify-center p-6">
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm max-w-md w-full p-8">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-blue-600">
            University Intelligent Communication Hub
          </p>
          <h1 className="text-xl font-bold text-slate-900 mt-2">Sign in to Smart Query Desk</h1>
          <p className="text-xs text-slate-500 mt-2 leading-relaxed">
            Describe any problem in plain words and it reaches the right office automatically.
            Sign in with your Google account; no password is ever stored.
          </p>
          <div className="mt-6 space-y-4">
            <Alert onClose={() => setError("")}>{error}</Alert>
            <div className="flex justify-center min-h-[44px]" ref={buttonRef} />
            {busy && <p className="text-xs text-center text-slate-500">Signing you in...</p>}
          </div>
        </div>
      </main>

      <footer className="py-4 text-center text-[11px] text-slate-400">
        CS619 Final Year Project · Smart Query Routing &amp; Email Automation System
      </footer>
    </div>
  );
}


// --- Page header and notification bell ---------------------------------------

function NotificationBell() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [fresh, setFresh] = useState(new Set());

  const load = useCallback(() => {
    api("/notifications?limit=30").then(setItems).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);

  const unread = items.filter((item) => !item.is_read);

  function toggle() {
    if (open) return setOpen(false);
    setOpen(true);
    if (unread.length) {
      // Highlight what was new for this viewing, and mark everything read on the server.
      setFresh(new Set(unread.map((item) => item.notification_id)));
      setItems(items.map((item) => ({ ...item, is_read: true })));
      api("/notifications/read-all", { method: "POST" }).catch(() => {});
    }
  }

  return (
    <div className="relative">
      <Button variant="secondary" onClick={toggle} className="relative">
        Notifications
        {unread.length > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-600 text-white text-[10px] font-bold flex items-center justify-center">
            {unread.length}
          </span>
        )}
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-2 w-96 max-w-[90vw] bg-white border border-slate-200 rounded-xl shadow-xl z-50">
            <div className="px-4 py-3 border-b border-slate-200 text-xs font-semibold text-slate-900">Notifications</div>
            <div className="max-h-96 overflow-y-auto divide-y divide-slate-100">
              {items.length === 0 ? (
                <EmptyState>No notifications yet.</EmptyState>
              ) : (
                items.map((item) => (
                  <div key={item.notification_id}
                       className={`px-4 py-3 text-xs ${fresh.has(item.notification_id) ? "bg-blue-50/70" : ""}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${
                        item.kind === "announcement" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>
                        {item.kind === "announcement" ? "Announcement" : "Update"}
                      </span>
                      <span className="text-[11px] text-slate-400">{timeAgo(item.sent_at)}</span>
                    </div>
                    {item.title && <p className="font-semibold text-slate-900">{item.title}</p>}
                    <p className="text-slate-700 leading-relaxed">{item.message}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function AppHeader({ user, onLogout }) {
  return (
    <header className="bg-white border-b border-slate-200 px-4 sm:px-6 py-3 flex items-center justify-between sticky top-0 z-30">
      <div className="flex items-center gap-3">
        <Logo />
        <div>
          <p className="text-sm font-semibold text-slate-900">Smart Query Desk</p>
          <p className="text-[11px] text-slate-500">
            {user.role}{user.department_name ? ` · ${user.department_name}` : ""}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <NotificationBell />
        <div className="text-right hidden sm:block">
          <p className="text-xs font-semibold text-slate-900">{user.name}</p>
          <p className="text-[11px] text-slate-500">{user.email}</p>
        </div>
        <Button variant="secondary" onClick={onLogout}>Sign out</Button>
      </div>
    </header>
  );
}