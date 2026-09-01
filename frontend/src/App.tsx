import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Loading from "./components/Loading";
import ErrorDisplay from "./components/ErrorDisplay";
import { fetchCurrentUser, logout, type CurrentUser } from "./api";
import ReposList from "./pages/ReposList";
import RepoDetail from "./pages/RepoDetail";
import PRDetail from "./pages/PRDetail";

export default function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCurrentUser().then(setUser).catch((err) => setError(err.message)).finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading text="Checking GitHub session..." />;
  if (error) return <main className="main"><ErrorDisplay message={error} /></main>;
  if (!user) return (
    <main className="login-page">
      <div className="login-card">
        <span className="logo-icon">◆</span>
        <h1>PRism</h1>
        <p>Sign in to view analysis for repositories you collaborate on.</p>
        <a className="github-login" href="/api/auth/login">Sign in with GitHub</a>
      </div>
    </main>
  );

  const handleLogout = async () => {
    await logout();
    setUser(null);
  };

  return (
    <BrowserRouter>
      <Layout user={user} onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<ReposList />} />
          <Route path="/repos/:repoId" element={<RepoDetail />} />
          <Route path="/repos/:repoId/pull-requests/:prNumber" element={<PRDetail />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
