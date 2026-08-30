import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import ReposList from "./pages/ReposList";
import RepoDetail from "./pages/RepoDetail";
import PRDetail from "./pages/PRDetail";

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<ReposList />} />
          <Route path="/repos/:repoId" element={<RepoDetail />} />
          <Route path="/repos/:repoId/pull-requests/:prNumber" element={<PRDetail />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
