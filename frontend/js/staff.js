/*
 * Staff workbench (SRS sections 6.2 to 6.4): the queue for Instructors, HODs
 * and department staff. The Admin console reuses it for every query.
 *
 * Pick a query, check how the AI classified it, edit the AI-drafted reply and
 * send it, or move the query on: ask the student for more information,
 * escalate, reassign or take ownership. Instructors also manage their leave here.
 */

const STAFF_REFRESH_MS = 30000;
const QUEUE_FILTERS = ["Open", ...STATUSES, "All"];
const AI_CONFIDENT = 0.7; // the same threshold as AI_CONFIDENCE_THRESHOLD in the backend

function inQueueFilter(query, filter) {
  if (filter === "All") return true;
  if (filter === "Open") return query.status !== "Resolved";
  return query.status === filter;
}

function StaffWorkbench({ user, onUserChange }) {
  const { data: queries, error, loading, reload } = useApi("/queries?limit=200");
  const [filter, setFilter] = useState("Open");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    const timer = setInterval(reload, STAFF_REFRESH_MS);
    return () => clearInterval(timer);
  }, [reload]);

  const list = queries || [];
  const term = search.trim().toLowerCase();
  const shown = list.filter((query) =>
    inQueueFilter(query, filter) &&
    (!term || [query.reference_code, query.student_name, query.query_text]
      .some((value) => value.toLowerCase().includes(term))));

  return (
    <div className="space-y-5">
      {user.role === "Instructor" && <LeavePanel user={user} onUserChange={onUserChange} />}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        <div className="lg:col-span-5 space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {QUEUE_FILTERS.map((name) => (
              <button
                key={name}
                onClick={() => setFilter(name)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium border transition ${filter === name
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"}`}
              >
                {name} <span className="opacity-60">{list.filter((query) => inQueueFilter(query, name)).length}</span>
              </button>
            ))}
          </div>
          <input value={search} onChange={(event) => setSearch(event.target.value)}
                 placeholder="Search by reference, student or text..." className={INPUT_CLASS} />
          <QueueList queries={shown} loading={loading && !queries} error={error}
                     selectedId={selectedId} onSelect={setSelectedId} />
        </div>

        <div className="lg:col-span-7 lg:sticky lg:top-20">
          {selectedId ? (
            <QueryWorkspace key={selectedId} queryId={selectedId} user={user} onChanged={reload} />
          ) : (
            <Card><EmptyState>Select a query from the queue to review it.</EmptyState></Card>
          )}
        </div>
      </div>
    </div>
  );
}


// --- The queue ---------------------------------------------------------------

function QueueList({ queries, loading, error, selectedId, onSelect }) {
  return (
    <Card bodyClassName="p-0">
      {error && <div className="p-4"><Alert>{error}</Alert></div>}
      {loading ? (
        <Loading />
      ) : queries.length === 0 ? (
        <EmptyState>No queries here.</EmptyState>
      ) : (
        <ul className="divide-y divide-slate-100 max-h-[640px] overflow-y-auto">
          {queries.map((query) => (
            <li key={query.query_id}>
              <button
                onClick={() => onSelect(query.query_id)}
                className={`w-full text-left px-4 py-3.5 border-l-4 transition ${selectedId === query.query_id
                  ? "bg-slate-100 border-slate-900"
                  : "border-transparent hover:bg-slate-50"}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-900">{query.reference_code}</span>
                    <CategoryPill category={query.category} />
                  </div>
                  <StatusBadge status={query.status} />
                </div>
                {query.intent && <p className="text-xs font-medium text-slate-800 mt-1.5">{query.intent}</p>}
                <p className="text-xs text-slate-600 mt-1 line-clamp-2">{query.query_text}</p>
                <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-slate-400">
                  <span>{query.student_name}</span>
                  <span>{query.assigned_to_name ? `With ${query.assigned_to_name}` : "Unassigned"}</span>
                  <span>{timeAgo(query.updated_at)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}


// --- Working on one query ----------------------------------------------------

function AiBadge({ query }) {
  if (query.ai_confidence == null) return null;
  const confident = query.ai_confidence >= AI_CONFIDENT;
  return (
    <span
      title="The AI's category, how sure it was, and which step of the pipeline decided"
      className={`text-[11px] font-medium px-2 py-1 rounded border whitespace-nowrap ${confident
        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
        : "bg-amber-50 text-amber-700 border-amber-200"}`}
    >
      AI: {query.category} · {Math.round(query.ai_confidence * 100)}% · {query.routing_method}
    </span>
  );
}

function QueryWorkspace({ queryId, user, onChanged }) {
  const { data: query, error, loading, reload } = useApi(`/queries/${queryId}`);
  const [draft, setDraft] = useState("");
  const [dialog, setDialog] = useState(null); // "more-info", "resolve", "escalate" or "reassign"
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");

  // Put the AI draft into the editor once the query has loaded.
  const loadedId = query ? query.query_id : null;
  useEffect(() => {
    if (query) setDraft(query.ai_draft || "");
  }, [loadedId]);

  if (loading && !query) return <Card><Loading /></Card>;
  if (!query) return <Card><Alert>{error || "This query could not be loaded."}</Alert></Card>;

  const path = `/queries/${query.query_id}`;
  const isOpen = query.status !== "Resolved";
  const canAct = query.can_act && isOpen;
  const canTakeOver = canAct && ["HOD", "Admin"].includes(user.role) && query.assigned_to_name !== user.name;

  // Every action returns a short message from the backend, shown once the action succeeds.
  function finish(result) {
    setDialog(null);
    setNotice(result.message);
    reload();
    onChanged();
  }

  async function perform(request) {
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      finish(await request());
    } catch (err) {
      setActionError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const changeStatus = (status, note) => api(`${path}/status`, { method: "PATCH", body: { status, note } });
  const sendReply = () => perform(() => api(`${path}/reply`, { method: "POST", body: { text: draft.trim() } }));
  const markInProgress = () => perform(() => changeStatus("In Progress"));
  const takeOwnership = () => perform(() => api(`${path}/take-ownership`, { method: "POST" }));

  return (
    <Card
      title={`Query ${query.reference_code}`}
      subtitle={`From ${query.student_name} · ${query.assigned_to_name ? `with ${query.assigned_to_name}` : "unassigned"}`}
      actions={<AiBadge query={query} />}
    >
      <div className="space-y-5">
        {query.intent && (
          <p className="text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
            <span className="font-semibold">AI summary:</span> {query.intent}
          </p>
        )}
        {notice && <Alert type="success" onClose={() => setNotice("")}>{notice}</Alert>}
        <Alert onClose={() => setActionError("")}>{actionError}</Alert>
        {!query.can_act && isOpen && (
          <Alert type="info">
            You can follow this query, but it is handled by {query.assigned_to_name || "another team"}.
          </Alert>
        )}

        {canAct && (
          <div>
            <div className="flex items-center justify-between">
              <h4 className={LABEL_CLASS}>Reply to the student</h4>
              {query.ai_draft && draft !== query.ai_draft && (
                <button onClick={() => setDraft(query.ai_draft)} className="text-[11px] text-blue-600 hover:underline mb-1.5">
                  Restore AI draft
                </button>
              )}
            </div>
            <textarea rows={8} value={draft} maxLength={5000} onChange={(event) => setDraft(event.target.value)}
                      placeholder="Write the reply to the student..." className={`${INPUT_CLASS} leading-relaxed`} />
            <p className="text-[11px] text-slate-400 mt-1">
              {query.ai_draft
                ? "Drafted by AI. Check every detail before sending; nothing reaches the student without your approval."
                : "No AI draft is available for this query; please write the reply yourself."}
            </p>
            <div className="mt-3">
              <Button onClick={sendReply} disabled={busy || !draft.trim()}>
                {busy ? "Working..." : "Approve and send reply"}
              </Button>
            </div>
          </div>
        )}

        {canAct && (
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
            {query.status !== "In Progress" && (
              <Button variant="secondary" disabled={busy} onClick={markInProgress}>Mark in progress</Button>
            )}
            {query.status !== "Needs More Info" && (
              <Button variant="secondary" disabled={busy} onClick={() => setDialog("more-info")}>
                Ask student for more info
              </Button>
            )}
            <Button variant="secondary" disabled={busy} onClick={() => setDialog("reassign")}>Reassign</Button>
            <Button variant="secondary" disabled={busy} onClick={() => setDialog("resolve")}>Resolve without reply</Button>
            {query.status !== "Escalated" && (
              <Button variant="danger" disabled={busy} onClick={() => setDialog("escalate")}>Escalate</Button>
            )}
            {canTakeOver && (
              <Button variant="warning" disabled={busy} onClick={takeOwnership}>Take ownership</Button>
            )}
          </div>
        )}

        <QueryOverview query={query} />
      </div>

      {dialog === "more-info" && (
        <TextActionDialog
          title="Ask the student for more information"
          description="The student sees your question on their dashboard and by email. The query waits for their answer."
          label="What do you need from the student?"
          confirmText="Send question"
          onClose={() => setDialog(null)}
          onSubmit={async (note) => finish(await changeStatus("Needs More Info", note))}
        />
      )}
      {dialog === "resolve" && (
        <TextActionDialog
          title="Resolve without a written reply"
          description="Use this when the problem was solved another way, for example by phone or in person."
          label="How was it resolved?"
          confirmText="Resolve query"
          onClose={() => setDialog(null)}
          onSubmit={async (note) => finish(await changeStatus("Resolved", note))}
        />
      )}
      {dialog === "escalate" && (
        <TextActionDialog
          title="Escalate this query"
          description="It moves to the HOD for academic departments, or to an Administrator for the service desks."
          label="Why does it need a senior person?"
          minLength={5}
          confirmText="Escalate"
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => finish(await api(`${path}/escalate`, { method: "POST", body: { reason } }))}
        />
      )}
      {dialog === "reassign" && (
        <ReassignDialog
          query={query}
          onClose={() => setDialog(null)}
          onSubmit={async (assigneeId, reason) => finish(await api(`${path}/reassign`, {
            method: "POST", body: { assignee_id: assigneeId, reason },
          }))}
        />
      )}
    </Card>
  );
}


// --- Action dialogs ----------------------------------------------------------

function TextActionDialog({ title, description, label, minLength = 1, confirmText, onSubmit, onClose }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit(text.trim()); // on success the parent closes this dialog
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {description && <p className="text-xs text-slate-500">{description}</p>}
        <Field label={label}>
          <textarea rows={3} autoFocus value={text} maxLength={255}
                    onChange={(event) => setText(event.target.value)} className={INPUT_CLASS} />
        </Field>
        <Alert onClose={() => setError("")}>{error}</Alert>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || text.trim().length < minLength}>
            {busy ? "Saving..." : confirmText}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ReassignDialog({ query, onSubmit, onClose }) {
  const { data: staff, error: loadError, loading } = useApi("/users/staff");
  const [assigneeId, setAssigneeId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const people = (staff || []).filter((person) => person.name !== query.assigned_to_name);
  const chosen = people.find((person) => String(person.user_id) === assigneeId);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit(Number(assigneeId), reason.trim() || null);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Modal title="Reassign this query" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Alert>{loadError}</Alert>
        <Field label="Hand it to">
          <select required value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)} className={INPUT_CLASS}>
            <option value="">{loading ? "Loading staff..." : "Choose a staff member"}</option>
            {people.map((person) => (
              <option key={person.user_id} value={person.user_id}>
                {person.name} · {person.role}{person.department_name ? `, ${person.department_name}` : ""}
                {person.on_leave ? " (on leave)" : ""}
              </option>
            ))}
          </select>
        </Field>
        {chosen && chosen.on_leave && (
          <Alert type="info">
            {chosen.name} is on leave until {formatDateTime(chosen.leave_until)}. The query will wait until they return.
          </Alert>
        )}
        <Field label="Reason (optional)">
          <input value={reason} maxLength={255} onChange={(event) => setReason(event.target.value)} className={INPUT_CLASS} />
        </Field>
        <Alert onClose={() => setError("")}>{error}</Alert>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || !assigneeId}>{busy ? "Saving..." : "Reassign"}</Button>
        </div>
      </form>
    </Modal>
  );
}


// --- Instructor leave (FR-13) ------------------------------------------------

// A date as "YYYY-MM-DDTHH:MM" in Pakistan time, the format a datetime-local input uses.
function toPakistanInput(date) {
  return new Date(date.getTime() + 5 * 60 * 60 * 1000).toISOString().slice(0, 16);
}

function LeavePanel({ user, onUserChange }) {
  const [editing, setEditing] = useState(false);
  const [from, setFrom] = useState(() => toPakistanInput(new Date()));
  const [until, setUntil] = useState(() => toPakistanInput(new Date(Date.now() + 2 * 24 * 60 * 60 * 1000)));
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const planned = user.leave_until && new Date(user.leave_until) > new Date();

  async function update(request) {
    setBusy(true);
    setError("");
    try {
      const result = await request();
      onUserChange({
        ...user,
        on_leave: result.on_leave,
        leave_from: result.leave_from,
        leave_until: result.leave_until,
        auto_reply_message: result.auto_reply_message,
      });
      setEditing(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function startLeave(event) {
    event.preventDefault();
    update(() => api("/users/me/auto-reply", {
      method: "PATCH",
      body: { leave_from: `${from}:00`, leave_until: `${until}:00`, auto_reply_message: message.trim() || null },
    }));
  }

  const endLeave = () => update(() => api("/users/me/auto-reply", { method: "DELETE" }));

  return (
    <Card title="Leave and auto-reply"
          subtitle="While you are on leave, new queries go to a colleague and students receive your auto-reply.">
      <div className="space-y-3">
        <Alert onClose={() => setError("")}>{error}</Alert>
        {planned ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-slate-700">
              <p className="font-semibold">
                {user.on_leave ? "You are on leave" : "Leave planned"}: {formatDateTime(user.leave_from)} to {formatDateTime(user.leave_until)}
              </p>
              {user.auto_reply_message && <p className="text-slate-500 mt-1">Auto-reply: "{user.auto_reply_message}"</p>}
            </div>
            <Button variant="secondary" disabled={busy} onClick={endLeave}>
              {user.on_leave ? "End leave now" : "Cancel leave"}
            </Button>
          </div>
        ) : !editing ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-slate-600">You are available and receiving new queries.</p>
            <Button onClick={() => setEditing(true)}>Plan a leave</Button>
          </div>
        ) : (
          <form onSubmit={startLeave} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="From">
              <input type="datetime-local" required value={from}
                     onChange={(event) => setFrom(event.target.value)} className={INPUT_CLASS} />
            </Field>
            <Field label="Until">
              <input type="datetime-local" required value={until}
                     onChange={(event) => setUntil(event.target.value)} className={INPUT_CLASS} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Auto-reply message (optional)"
                     hint="Leave it empty to use a standard message with your return date.">
                <textarea rows={2} maxLength={500} value={message}
                          onChange={(event) => setMessage(event.target.value)} className={INPUT_CLASS} />
              </Field>
            </div>
            <div className="sm:col-span-2 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditing(false)}>Cancel</Button>
              <Button type="submit" disabled={busy}>{busy ? "Saving..." : "Start leave"}</Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}