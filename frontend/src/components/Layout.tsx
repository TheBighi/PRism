import { Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

export default function Layout({ children }: { children: ReactNode }) {
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
          </nav>
        </div>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}
