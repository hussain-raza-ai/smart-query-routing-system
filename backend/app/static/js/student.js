/*
 * Student portal (SRS section 6.1): submit a query in plain words, follow
 * its progress, answer "more information" requests and ask the FAQ assistant.
 */

const STUDENT_REFRESH_MS = 15000; // SRS UC-03: the list refreshes every 15 seconds
const MAX_QUERY_LENGTH = 2000;

function StudentPortal({ user }) {
  const { data: queries, error, loading, reload } = useApi("/queries?limit=100");
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    const timer = setInterval(reload, STUDENT_REFRESH_MS);
    return () => clearInterval(timer);
  }, [reload]);

  const list = queries || [];
  const counts = {
    open: list.filter((query) => query.status !== "Resolved").length,
    waiting: list.filter((query) => query.status === "Needs More Info").length,
    resolved: list.filter((query) => query.status === "Resolved").length,
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-4 space-y-6">
          <SubmitQueryCard onSubmitted={reload} />
          <StudentStats counts={counts} />
        </div>
        <div className="lg:col-span-8">
          <MyQueriesCard queries={list} loading={loading && !queries} error={error} onOpen={setOpenId} />
        </div>
      </div>

      {openId && (
        <StudentQueryModal queryId={openId} onClose={() => setOpenId(null)} onChanged={reload} />
      )}
      <FaqAssistant firstName={user.name.split(" ")[0]} />
    </div>
  );
}


// --- Submitting a query ------------------------------------------------------

function SubmitQueryCard({ onSubmitted }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function submit(event) {
    event.preventDefault();
    const queryText = text.trim();
    if (queryText.length < 10) {
      setError("Please describe your problem in at least 10 characters.");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const query = await api("/queries", { method: "POST", body: { query_text: queryText } });
      setResult(query);
      setText("");
      onSubmitted();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Submit a new query"
          subtitle="Describe your problem in your own words. You do not need to choose a department.">
      <form onSubmit={submit} className="space-y-3">
        <textarea
          rows={6}
          value={text}
          maxLength={MAX_QUERY_LENGTH}
          onChange={(event) => setText(event.target.value)}
          placeholder="e.g. My CS101 midterm result shows absent although I attended the exam."
          className={`${INPUT_CLASS} leading-relaxed`}
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-400">{text.length}/{MAX_QUERY_LENGTH}</span>
          <Button type="submit" disabled={busy}>
            {busy ? "Classifying and routing..." : "Submit query"}
          </Button>
        </div>
        <Alert onClose={() => setError("")}>{error}</Alert>
        {result && (
          <Alert type="success" onClose={() => setResult(null)}>
            Query <strong>{result.reference_code}</strong> was received as <strong>{result.category}</strong> and
            sent to {result.department_name || "an administrator for review"}. A confirmation email is on its way.
          </Alert>
        )}
      </form>
    </Card>
  );
}

function StudentStats({ counts }) {
  const items = [
    ["Open", counts.open, "text-slate-900"],
    ["Waiting for you", counts.waiting, "text-violet-700"],
    ["Resolved", counts.resolved, "text-emerald-700"],
  ];
  return (
    <div className="grid grid-cols-3 gap-3">
      {items.map(([label, value, color]) => (
        <div key={label} className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <p className="text-[11px] text-slate-500">{label}</p>
          <p className={`text-xl font-bold mt-1 ${color}`}>{value}</p>
        </div>
      ))}
    </div>
  );
}


// --- The student's queries ---------------------------------------------------

function MyQueriesCard({ queries, loading, error, onOpen }) {
  const [filter, setFilter] = useState("All");
  const shown = filter === "All" ? queries : queries.filter((query) => query.status === filter);

  return (
    <Card
      title="My queries"
      subtitle="Updates every 15 seconds. Click a query to see its full history."
      bodyClassName="p-0"
      actions={
        <select value={filter} onChange={(event) => setFilter(event.target.value)}
                className="px-2.5 py-1.5 border border-slate-300 rounded-lg text-xs bg-white">
          {["All", ...STATUSES].map((status) => <option key={status}>{status}</option>)}
        </select>
      }
    >
      {error && <div className="p-4"><Alert>{error}</Alert></div>}
      {loading ? (
        <Loading />
      ) : shown.length === 0 ? (
        <EmptyState>
          {queries.length ? "No queries with this status." : "You have not submitted any queries yet."}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-slate-100">
          {shown.map((query) => {
            const needsReply = query.status === "Needs More Info";
            return (
              <li key={query.query_id}>
                <button
                  onClick={() => onOpen(query.query_id)}
                  className={`w-full text-left px-5 py-4 hover:bg-slate-50 transition ${needsReply ? "bg-violet-50/60" : ""}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-slate-900">{query.reference_code}</span>
                      <CategoryPill category={query.category} />
                    </div>
                    <StatusBadge status={query.status} />
                  </div>
                  <p className="text-xs text-slate-600 mt-1.5 line-clamp-2">{query.query_text}</p>
                  <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-slate-400">
                    <span>{query.department_name || "Awaiting review"}</span>
                    <span>Updated {timeAgo(query.updated_at)}</span>
                    {needsReply && <span className="text-violet-700 font-medium">Your reply is needed</span>}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function StudentQueryModal({ queryId, onClose, onChanged }) {
  const { data: query, error, loading, reload } = useApi(`/queries/${queryId}`);

  function handleInfoSent() {
    reload();
    onChanged();
  }

  return (
    <Modal title={query ? `Query ${query.reference_code}` : "Query"} onClose={onClose} wide>
      <Alert>{error}</Alert>
      {loading && !query ? (
        <Loading />
      ) : query && (
        <div className="space-y-5">
          {query.status === "Needs More Info" && <MoreInfoForm query={query} onSent={handleInfoSent} />}
          <QueryOverview query={query} />
        </div>
      )}
    </Modal>
  );
}

function MoreInfoForm({ query, onSent }) {
  // The staff member's question is the note on the latest "Needs More Info" step.
  const request = [...query.history].reverse().find((entry) => entry.new_status === "Needs More Info");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function send(event) {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api(`/queries/${query.query_id}/more-info`, { method: "POST", body: { text: text.trim() } });
      setText("");
      onSent();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={send} className="bg-violet-50 border border-violet-200 rounded-lg p-4 space-y-3">
      <div>
        <p className="text-xs font-semibold text-violet-900">The office needs more information from you</p>
        {request && request.note && (
          <p className="text-xs text-violet-800 mt-1 whitespace-pre-line">{request.note}</p>
        )}
      </div>
      <textarea rows={3} value={text} maxLength={MAX_QUERY_LENGTH}
                onChange={(event) => setText(event.target.value)}
                placeholder="Write the information here..." className={INPUT_CLASS} />
      <Alert onClose={() => setError("")}>{error}</Alert>
      <Button type="submit" disabled={busy || !text.trim()}>
        {busy ? "Sending..." : "Send information"}
      </Button>
    </form>
  );
}


// --- FAQ assistant -----------------------------------------------------------

function FaqAssistant({ firstName }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [messages, setMessages] = useState([
    { from: "assistant",
      text: `Hi ${firstName}! Ask me a general question, for example who handles fee challans or how long a reply takes.` },
  ]);
  const endRef = useRef(null);

  useEffect(() => {
    if (endRef.current) endRef.current.scrollIntoView({ block: "nearest" });
  }, [messages, open]);

  async function ask(event) {
    event.preventDefault();
    const text = question.trim();
    if (text.length < 3 || asking) return;
    setMessages((list) => [...list, { from: "student", text }]);
    setQuestion("");
    setAsking(true);
    try {
      const { answer } = await api("/assistant/ask", { method: "POST", body: { question: text } });
      setMessages((list) => [...list, { from: "assistant", text: answer }]);
    } catch (err) {
      setMessages((list) => [...list, {
        from: "assistant", text: "Sorry, I could not answer right now. Please submit your question as a query.",
      }]);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="fixed bottom-5 right-5 z-40 flex flex-col items-end gap-3">
      {open && (
        <div className="w-80 max-w-[calc(100vw-2.5rem)] bg-white border border-slate-200 rounded-xl shadow-xl overflow-hidden">
          <div className="bg-slate-900 text-white px-4 py-3 flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold">AI help desk</p>
              <p className="text-[10px] text-slate-400">Answers general questions instantly</p>
            </div>
            <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-white text-sm">✕</button>
          </div>
          <div className="h-72 overflow-y-auto p-3 space-y-2.5 bg-slate-50 text-xs">
            {messages.map((message, index) => (
              <div key={index}
                   className={`p-2.5 rounded-lg leading-relaxed ${message.from === "student"
                     ? "bg-slate-900 text-white ml-8"
                     : "bg-white border border-slate-200 text-slate-700 mr-6"}`}>
                {message.text}
              </div>
            ))}
            {asking && <p className="text-[11px] text-slate-400 px-1">Thinking...</p>}
            <div ref={endRef} />
          </div>
          <form onSubmit={ask} className="p-2.5 border-t border-slate-200 flex gap-2">
            <input
              value={question}
              maxLength={500}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask a question..."
              className="flex-1 px-2.5 py-1.5 border border-slate-300 rounded-md text-xs focus:outline-none focus:border-slate-900"
            />
            <Button type="submit" disabled={asking || question.trim().length < 3}>Send</Button>
          </form>
        </div>
      )}
      <button onClick={() => setOpen(!open)}
              className="px-4 py-2.5 bg-slate-900 hover:bg-slate-800 text-white rounded-full shadow-lg text-xs font-medium">
        {open ? "Close help desk" : "Ask the AI help desk"}
      </button>
    </div>
  );
}