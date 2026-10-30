/*
 * Entry point: signs the user in, then shows the dashboard for their role.
 * Loaded last, after core.js and the three role files.
 */

function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(getToken()));

  // A saved token from an earlier visit: confirm it is still valid.
  useEffect(() => {
    if (!getToken()) return;
    api("/auth/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setChecking(false));
  }, []);

  // Any request that finds the token expired sends the user back to sign in.
  useEffect(() => {
    const signOut = () => setUser(null);
    window.addEventListener("session-expired", signOut);
    return () => window.removeEventListener("session-expired", signOut);
  }, []);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    clearToken();
    setUser(null);
  }

  if (checking) return <Loading text="Opening your dashboard..." />;
  if (!user) return <LoginView onLogin={setUser} />;

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader user={user} onLogout={logout} />
      <main className="flex-1 w-full max-w-7xl mx-auto p-4 sm:p-6">
        {user.role === "Student" && <StudentPortal user={user} />}
        {["Instructor", "DepartmentStaff"].includes(user.role) && (
          <StaffWorkbench user={user} onUserChange={setUser} />
        )}
        {user.role === "HOD" && <HodDashboard user={user} onUserChange={setUser} />}
        {user.role === "Admin" && <AdminConsole user={user} />}
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);