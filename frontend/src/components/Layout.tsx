import { Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import type { CurrentUser } from "../api";

export default function Layout({ children, user, onLogout }: {
  children: ReactNode;
  user: CurrentUser;
  onLogout: () => Promise<void>;
}) {
  const location = useLocation();

  return (
    <div className="layout">
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="logo">
            <span className="logo-icon">◈</span> PRism
          </Link>
          <nav className="nav">
            <Link
              to="/"
              className={`nav-link ${location.pathname === "/" ? "active" : ""}`}
            >
              Repos
            </Link>
            <span className="nav-user">
              {user.avatar_url && <img src={user.avatar_url} alt="" />}
              {user.login}
            </span>
            <button className="logout-button" onClick={() => void onLogout()}>Sign out</button>
          </nav>
        </div>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}
