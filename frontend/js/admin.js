/*
 * Admin console (SRS section 6.5) and the HOD's department dashboard.
 *
 * Admin tabs: analytics and reports, every query, users and roles, AI routing
 * rules, announcements and the audit log. HODs get their queue plus the
 * analytics tab, which the backend limits to their own department.
 */

const ADMIN_TABS = [
  ["overview", "Analytics"],
  ["queries", "All queries"],
  ["users", "Users"],
  ["routing", "Routing rules"],
  ["broadcast", "Announcements"],
  ["audit", "Audit log"],
];
const ROLES = ["Student", "Instructor", "HOD", "DepartmentStaff", "Admin"];
// The kind of department each staff role works in (the backend checks the same rule).
const ROLE_DEPARTMENT_TYPES = {
  Instructor: ["Academic"],
  HOD: ["Academic"],
  DepartmentStaff: ["Exam", "Registrar", "Finance", "IT"],
};
const AUDIT_ACTIONS = [
  "LOGIN", "LOGOUT", "USER_REGISTERED", "USER_CREATED", "USER_UPDATED",
  "QUERY_SUBMITTED", "QUERY_ROUTED", "STATUS_CHANGED", "STUDENT_ADDED_INFO", "REPLY_SENT",
  "QUERY_ESCALATED", "QUERY_REASSIGNED", "LEAVE_SET", "LEAVE_CANCELLED",
  "ANNOUNCEMENT_SENT", "REPORT_EXPORTED", "AUDIT_LOG_EXPORTED", "ROUTING_RULE_UPDATED",
  "SLA_CHECK_RUN", "DAILY_SUMMARY_SENT", "DEMO_DATA_RESET",
];
const AUDIT_PAGE_SIZE = 25;
const CHART_COLORS = { dark: "#0f172a", blue: "#2563eb", amber: "#f59e0b" };


// --- Layout ------------------------------------------------------------------

function TabBar({ tabs, active, onChange }) {
  return (
    <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
      {tabs.map(([id, label]) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          className={`px-3.5 py-2 rounded-lg text-xs font-medium transition ${active === id
            ? "bg-slate-900 text-white"
            : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function AdminConsole({ user }) {
  const [tab, setTab] = useState("overview");
  return (
    <div className="space-y-5">
      <TabBar tabs={ADMIN_TABS} active={tab} onChange={setTab} />
      {tab === "overview" && <AnalyticsPanel user={user} />}
      {tab === "queries" && <StaffWorkbench user={user} />}
      {tab === "users" && <UsersPanel user={user} />}
      {tab === "routing" && <RoutingRulesPanel />}
      {tab === "broadcast" && <BroadcastPanel />}
      {tab === "audit" && <AuditLogPanel />}
    </div>
  );
}

function HodDashboard({ user, onUserChange }) {
  const [tab, setTab] = useState("queue");
  return (
    <div className="space-y-5">
      <TabBar tabs={[["queue", "Department queries"], ["overview", "Department analytics"]]}
              active={tab} onChange={setTab} />
      {tab === "queue"
        ? <StaffWorkbench user={user} onUserChange={onUserChange} />
        : <AnalyticsPanel user={user} />}
    </div>
  );
}


// --- Analytics and reports (FR-10, FR-12) ------------------------------------

// "YYYY-MM-DD" for today in Pakistan, moved by `offsetDays`.
function pakistanDate(offsetDays = 0) {
  return new Date(Date.now() + 5 * 3600000 + offsetDays * 86400000).toISOString().slice(0, 10);
}

function formatHours(hours) {
  return hours < 1 ? `${Math.round(hours * 60)} min` : `${hours} h`;
}

function AnalyticsPanel({ user }) {
  const isAdmin = user.role === "Admin";
  const [dateFrom, setDateFrom] = useState(pakistanDate(-29));
  const [dateTo, setDateTo] = useState(pakistanDate(0));
  const [departmentId, setDepartmentId] = useState("");
  const [exporting, setExporting] = useState("");
  const [notice, setNotice] = useState(null);
  const { data: departments } = useApi(isAdmin ? "/departments" : null);

  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
  if (departmentId) params.set("department_id", departmentId);
  const filters = params.toString();
  const { data: stats, error, loading } = useApi(`/analytics/overview?${filters}`);

  async function exportReport(format) {
    setExporting(format);
    try {
      await downloadFile(`/reports/export?format=${format}&${filters}`, `query-report.${format}`);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setExporting("");
    }
  }
  async function sendDailySummary() {
    try {
      const result = await api("/automation/daily-summary/run-now", { method: "POST" });
      setNotice({ type: "success", text: `Daily summary emailed to ${result.recipients} HOD/Admin account(s).` });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  async function runSlaCheck() {
    try {
      const result = await api("/automation/sla-check/run-now", { method: "POST" });
      setNotice({
        type: "success",
        text: result.escalated
          ? `Escalated ${result.escalated} overdue query(s): ${result.reference_codes.join(", ")}`
          : "No query is overdue right now.",
      });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  }

  return (
    <div className="space-y-5">
      <Card bodyClassName="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-40">
            <Field label="From">
              <input type="date" value={dateFrom} max={dateTo}
                     onChange={(event) => setDateFrom(event.target.value)} className={INPUT_CLASS} />
            </Field>
          </div>
          <div className="w-40">
            <Field label="To">
              <input type="date" value={dateTo} min={dateFrom}
                     onChange={(event) => setDateTo(event.target.value)} className={INPUT_CLASS} />
            </Field>
          </div>
          {isAdmin && (
            <div className="w-56">
              <Field label="Department">
                <select value={departmentId} onChange={(event) => setDepartmentId(event.target.value)} className={INPUT_CLASS}>
                  <option value="">All departments</option>
                  {(departments || []).map((department) => (
                    <option key={department.department_id} value={department.department_id}>{department.name}</option>
                  ))}
                </select>
              </Field>
            </div>
          )}
          <div className="flex flex-wrap gap-2 ml-auto">
            <Button variant="secondary" disabled={Boolean(exporting)} onClick={() => exportReport("pdf")}>
              {exporting === "pdf" ? "Preparing..." : "Export PDF"}
            </Button>
            <Button variant="secondary" disabled={Boolean(exporting)} onClick={() => exportReport("xlsx")}>
              {exporting === "xlsx" ? "Preparing..." : "Export Excel"}
            </Button>
            {isAdmin && <Button variant="secondary" onClick={sendDailySummary}>Send daily summary</Button>}
            {isAdmin && <Button variant="danger" onClick={runSlaCheck}>Run SLA check now</Button>}
          </div>
        </div>
      </Card>

      {notice && <Alert type={notice.type} onClose={() => setNotice(null)}>{notice.text}</Alert>}
      <Alert>{error}</Alert>

      {loading && !stats ? (
        <Loading />
      ) : stats && (
        <>
          <KpiCards stats={stats} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Card title="Queries by category">
              <ChartCanvas
                type="bar"
                labels={stats.by_category.map((row) => row.category)}
                datasets={[{ label: "Queries", data: stats.by_category.map((row) => row.count),
                             backgroundColor: CHART_COLORS.dark, borderRadius: 6, maxBarThickness: 36 }]}
              />
            </Card>
            <Card title="Department workload" subtitle="All queries in the period, and how many are still open">
              <ChartCanvas
                type="bar"
                labels={stats.by_department.map((row) => row.department.split(" "))}
                datasets={[
                  { label: "Total", data: stats.by_department.map((row) => row.total),
                    backgroundColor: CHART_COLORS.dark, borderRadius: 6, maxBarThickness: 36 },
                  { label: "Still open", data: stats.by_department.map((row) => row.open),
                    backgroundColor: CHART_COLORS.amber, borderRadius: 6, maxBarThickness: 36 },
                ]}
              />
            </Card>
          </div>
          <Card title="Daily volume" subtitle="Queries submitted per day (Pakistan time)">
            <ChartCanvas
              type="line"
              labels={stats.daily_volume.map((row) =>
                new Date(`${row.day}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }))}
              datasets={[{ label: "Queries", data: stats.daily_volume.map((row) => row.count),
                           borderColor: CHART_COLORS.blue, backgroundColor: "rgba(37, 99, 235, 0.1)",
                           fill: true, tension: 0.3, pointRadius: 2 }]}
            />
          </Card>
        </>
      )}
    </div>
  );
}

function KpiCards({ stats }) {
  const counts = stats.status_counts;
  const cards = [
    ["Total queries", stats.total_queries, "text-slate-900"],
    ["Still open", stats.total_queries - counts["Resolved"], "text-amber-600"],
    ["Escalated", counts["Escalated"], "text-red-600"],
    ["Resolved", `${stats.resolution_rate}%`, "text-emerald-600"],
    ["Avg. first response", stats.avg_response_hours == null ? "N/A" : formatHours(stats.avg_response_hours), "text-slate-900"],
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      {cards.map(([label, value, color]) => (
        <div key={label} className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
        </div>
      ))}
    </div>
  );
}

function ChartCanvas({ type, labels, datasets, height = 240 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const chart = new Chart(canvasRef.current, {
      type,
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: datasets.length > 1, labels: { boxWidth: 12, font: { size: 11 } } } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0, color: "#64748b" }, grid: { color: "#f1f5f9" } },
          x: { ticks: { color: "#475569", font: { size: 11 }, maxRotation: 0, autoSkipPadding: 12 }, grid: { display: false } },
        },
      },
    });
    return () => chart.destroy();
  }, [type, JSON.stringify(labels), JSON.stringify(datasets)]);

  return <div style={{ height }}><canvas ref={canvasRef} /></div>;
}


// --- Users and roles ---------------------------------------------------------

function UsersPanel({ user }) {
  const { data: users, error, loading, reload } = useApi("/users");
  const { data: departments } = useApi("/departments");
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [editing, setEditing] = useState(null); // a user to edit, or "new"

  const term = search.trim().toLowerCase();
  const shown = (users || []).filter((person) =>
    (!roleFilter || person.role === roleFilter) &&
    (!term || person.name.toLowerCase().includes(term) || person.email.toLowerCase().includes(term)));

  function statusOf(person) {
    if (!person.is_active) return <span className="text-red-600">Deactivated</span>;
    if (person.on_leave) return <span className="text-amber-600">On leave</span>;
    return <span className="text-emerald-600">Active</span>;
  }

  return (
    <Card
      title="Users and roles"
      subtitle="Add accounts, change roles and departments, or deactivate an account. Changes apply immediately."
      bodyClassName="p-0"
      actions={<Button onClick={() => setEditing("new")}>Add user</Button>}
    >
      <div className="p-4 flex flex-wrap gap-3 border-b border-slate-100">
        <input value={search} onChange={(event) => setSearch(event.target.value)}
               placeholder="Search name or email..." className={`${INPUT_CLASS} max-w-xs`} />
        <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}
                className="px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white">
          <option value="">All roles</option>
          {ROLES.map((role) => <option key={role}>{role}</option>)}
        </select>
      </div>

      {error && <div className="p-4"><Alert>{error}</Alert></div>}
      {loading && !users ? (
        <Loading />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-3 px-4">Name</th>
                <th className="py-3 px-4">Email</th>
                <th className="py-3 px-4">Role</th>
                <th className="py-3 px-4">Department</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((person) => (
                <tr key={person.user_id} className="hover:bg-slate-50">
                  <td className="py-3 px-4 font-medium text-slate-900">{person.name}</td>
                  <td className="py-3 px-4 text-slate-600">{person.email}</td>
                  <td className="py-3 px-4">{person.role}</td>
                  <td className="py-3 px-4 text-slate-600">{person.department_name || "-"}</td>
                  <td className="py-3 px-4">{statusOf(person)}</td>
                  <td className="py-3 px-4 text-right">
                    {person.user_id === user.user_id
                      ? <span className="text-slate-400">You</span>
                      : <Button variant="secondary" onClick={() => setEditing(person)}>Edit</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <UserDialog
          person={editing === "new" ? null : editing}
          departments={departments || []}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload(); }}
        />
      )}
    </Card>
  );
}

function UserDialog({ person, departments, onClose, onSaved }) {
  const isNew = !person;
  const [name, setName] = useState(person ? person.name : "");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState(person ? person.role : "Student");
  const [departmentId, setDepartmentId] = useState(person && person.department_id ? String(person.department_id) : "");
  const [active, setActive] = useState(person ? person.is_active : true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const allowedTypes = ROLE_DEPARTMENT_TYPES[role];
  const departmentOptions = allowedTypes
    ? departments.filter((department) => allowedTypes.includes(department.type))
    : [];

  // Clear the department when it no longer fits the chosen role.
  useEffect(() => {
    if (departments.length && !departmentOptions.some((d) => String(d.department_id) === departmentId)) {
      setDepartmentId("");
    }
  }, [role, departments.length]);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const body = { name: name.trim(), role, department_id: allowedTypes ? Number(departmentId) || null : null };
    try {
      if (isNew) {
        await api("/users", { method: "POST", body: { ...body, email: email.trim() } });
      } else {
        await api(`/users/${person.user_id}`, { method: "PATCH", body: { ...body, is_active: active } });
      }
      onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal title={isNew ? "Add a user" : `Edit ${person.name}`} onClose={onClose}>
      <form onSubmit={save} className="space-y-3">
        <Field label="Full name">
          <input required minLength={2} maxLength={100} value={name}
                 onChange={(event) => setName(event.target.value)} className={INPUT_CLASS} />
        </Field>
        {isNew ? (
          <Field label="Email" hint="They sign in with Google using exactly this address.">
            <input required type="email" value={email}
                   onChange={(event) => setEmail(event.target.value)} className={INPUT_CLASS} />
          </Field>
        ) : (
          <p className="text-xs text-slate-500">{person.email}</p>
        )}
        <Field label="Role">
          <select value={role} onChange={(event) => setRole(event.target.value)} className={INPUT_CLASS}>
            {ROLES.map((roleName) => <option key={roleName}>{roleName}</option>)}
          </select>
        </Field>
        {allowedTypes && (
          <Field label="Department">
            <select required value={departmentId} onChange={(event) => setDepartmentId(event.target.value)}
                    className={INPUT_CLASS}>
              <option value="">Choose a department</option>
              {departmentOptions.map((department) => (
                <option key={department.department_id} value={department.department_id}>{department.name}</option>
              ))}
            </select>
          </Field>
        )}
        {!isNew && (
          <label className="flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />
            Account is active (untick to stop this person from signing in)
          </label>
        )}
        <Alert onClose={() => setError("")}>{error}</Alert>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? "Saving..." : isNew ? "Add user" : "Save changes"}</Button>
        </div>
      </form>
    </Modal>
  );
}


// --- AI routing rules --------------------------------------------------------

function RoutingRulesPanel() {
  const { data: rules, error, loading, reload } = useApi("/routing-rules");
  const { data: departments } = useApi("/departments");

  return (
    <Card title="AI routing rules"
          subtitle="Where each category detected by the AI is sent. Changes apply to the next query submitted."
          bodyClassName="p-0">
      {error && <div className="p-4"><Alert>{error}</Alert></div>}
      {loading && !rules ? (
        <Loading />
      ) : (
        <div className="divide-y divide-slate-100">
          {(rules || []).map((rule) => (
            <RoutingRuleRow key={rule.category} rule={rule} departments={departments || []} onSaved={reload} />
          ))}
        </div>
      )}
    </Card>
  );
}

function RoutingRuleRow({ rule, departments, onSaved }) {
  const [departmentId, setDepartmentId] = useState(String(rule.department_id));
  const [targetRole, setTargetRole] = useState(rule.target_role);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const changed = departmentId !== String(rule.department_id) || targetRole !== rule.target_role;
  const selectClass = "px-2.5 py-2 border border-slate-300 rounded-lg text-xs bg-white";

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api(`/routing-rules/${rule.category}`, {
        method: "PUT", body: { department_id: Number(departmentId), target_role: targetRole },
      });
      setMessage({ type: "success", text: "Saved" });
      onSaved();
    } catch (err) {
      setMessage({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-5 py-4 flex flex-wrap items-center gap-3">
      <div className="w-24"><CategoryPill category={rule.category} /></div>
      <select value={departmentId} onChange={(event) => setDepartmentId(event.target.value)} className={selectClass}>
        {departments.map((department) => (
          <option key={department.department_id} value={department.department_id}>{department.name}</option>
        ))}
      </select>
      <select value={targetRole} onChange={(event) => setTargetRole(event.target.value)} className={selectClass}>
            {["DepartmentStaff", "Instructor"].map((role) => <option key={role}>{role}</option>)}
      </select>
      <Button disabled={!changed || busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
      {message && (
        <span className={`text-xs ${message.type === "error" ? "text-red-600" : "text-emerald-600"}`}>{message.text}</span>
      )}
      <span className="text-[11px] text-slate-400 ml-auto">Updated {formatDateTime(rule.updated_at)}</span>
    </div>
  );
}


// --- Announcements (FR-11) ---------------------------------------------------

function BroadcastPanel() {
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [audience, setAudience] = useState("students");
  const [sendEmail, setSendEmail] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  async function send(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult("");
    try {
      const response = await api("/announcements", {
        method: "POST",
        body: { title: title.trim(), message: message.trim(), audience, send_email: sendEmail },
      });
      setResult(`Sent to ${response.recipients} user(s) on the dashboard` +
                (response.email_queued ? " and by email." : "."));
      setTitle("");
      setMessage("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Broadcast an announcement" className="max-w-2xl"
          subtitle="Reaches every active user in the chosen group through the notification bell, and by email if selected.">
      <form onSubmit={send} className="space-y-4">
        <Field label="Title">
          <input required minLength={3} maxLength={150} value={title}
                 onChange={(event) => setTitle(event.target.value)} className={INPUT_CLASS} />
        </Field>
        <Field label="Message">
          <textarea required rows={5} minLength={5} maxLength={2000} value={message}
                    onChange={(event) => setMessage(event.target.value)} className={INPUT_CLASS} />
        </Field>
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-48">
            <Field label="Send to">
              <select value={audience} onChange={(event) => setAudience(event.target.value)} className={INPUT_CLASS}>
                <option value="students">All students</option>
                <option value="staff">All staff</option>
                <option value="everyone">Everyone</option>
              </select>
            </Field>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-700 pb-2.5">
            <input type="checkbox" checked={sendEmail} onChange={(event) => setSendEmail(event.target.checked)} />
            Also send by email
          </label>
        </div>
        <Alert onClose={() => setError("")}>{error}</Alert>
        {result && <Alert type="success" onClose={() => setResult("")}>{result}</Alert>}
        <Button type="submit" disabled={busy}>{busy ? "Sending..." : "Send announcement"}</Button>
      </form>
    </Card>
  );
}


// --- Audit log (FR-14) -------------------------------------------------------

function AuditLogPanel() {
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(0);
  const [exportError, setExportError] = useState("");

  const filters = new URLSearchParams();
  if (action) filters.set("action", action);
  if (dateFrom) filters.set("date_from", dateFrom);
  if (dateTo) filters.set("date_to", dateTo);
  const filterText = filters.toString();
  const paging = `limit=${AUDIT_PAGE_SIZE}&offset=${page * AUDIT_PAGE_SIZE}`;
  const { data, error, loading } = useApi(`/audit-log?${paging}${filterText ? `&${filterText}` : ""}`);

  const total = data ? data.total : 0;
  const first = total ? page * AUDIT_PAGE_SIZE + 1 : 0;
  const last = Math.min(total, (page + 1) * AUDIT_PAGE_SIZE);

  // Changing a filter starts again from the first page.
  const filterBy = (setter) => (event) => { setter(event.target.value); setPage(0); };

  async function exportCsv() {
    setExportError("");
    try {
      await downloadFile(`/audit-log/export?${filterText}`, "audit-log.csv");
    } catch (err) {
      setExportError(err.message);
    }
  }

  return (
    <Card title="Audit log" subtitle="Every action that changed the system: who did it, on which query, and when."
          bodyClassName="p-0">
      <div className="p-4 flex flex-wrap items-end gap-3 border-b border-slate-100">
        <div className="w-56">
          <Field label="Action">
            <select value={action} onChange={filterBy(setAction)} className={INPUT_CLASS}>
              <option value="">All actions</option>
              {AUDIT_ACTIONS.map((name) => <option key={name}>{name}</option>)}
            </select>
          </Field>
        </div>
        <div className="w-40">
          <Field label="From">
            <input type="date" value={dateFrom} onChange={filterBy(setDateFrom)} className={INPUT_CLASS} />
          </Field>
        </div>
        <div className="w-40">
          <Field label="To">
            <input type="date" value={dateTo} onChange={filterBy(setDateTo)} className={INPUT_CLASS} />
          </Field>
        </div>
        <Button variant="secondary" className="ml-auto" onClick={exportCsv}>Export CSV</Button>
      </div>

      {(error || exportError) && <div className="p-4"><Alert>{error || exportError}</Alert></div>}
      {loading && !data ? (
        <Loading />
      ) : data && data.items.length === 0 ? (
        <EmptyState>No entries match these filters.</EmptyState>
      ) : data && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-3 px-4">Time</th>
                  <th className="py-3 px-4">Who</th>
                  <th className="py-3 px-4">Action</th>
                  <th className="py-3 px-4">Query</th>
                  <th className="py-3 px-4">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((entry) => (
                  <tr key={entry.log_id} className="align-top">
                    <td className="py-3 px-4 whitespace-nowrap text-slate-500">{formatDateTime(entry.timestamp)}</td>
                    <td className="py-3 px-4 whitespace-nowrap">{entry.actor}</td>
                    <td className="py-3 px-4">
                      <span className="font-mono text-[11px] bg-slate-100 px-1.5 py-0.5 rounded">{entry.action}</span>
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">{entry.reference_code || "-"}</td>
                    <td className="py-3 px-4 text-slate-600">{entry.details || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>Showing {first}–{last} of {total}</span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button variant="secondary" disabled={last >= total} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}