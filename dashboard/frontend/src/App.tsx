import { Link, NavLink, Route, Routes } from "react-router-dom";

import { ArticleDetailPage } from "./pages/ArticleDetailPage";
import { ArticlesPage } from "./pages/ArticlesPage";
import { EventDetailPage } from "./pages/EventDetailPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ToastProvider } from "./components/Toast";

/**
 * Root component. Phase 3 wires the full route tree:
 *
 *   /                  Overview (analytics landing page, req 3.1)
 *   /articles          Article list (Phase 2)
 *   /articles/:id      Article detail (req 3.7)
 *   /events/:id        Event detail (SPEC_ALERT_GROUPING.md req 2.4)
 *
 * The nav exposes both top-level destinations so the overview ↔ articles
 * round-trip in req 3.10 is one click in either direction.
 */
export function App() {
  return (
    <ToastProvider>
      <div className="app-shell">
        <nav className="app-nav" aria-label="Primary">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `app-nav-link ${isActive ? "app-nav-link-active" : ""}`
            }
          >
            Overview
          </NavLink>
          <NavLink
            to="/articles"
            className={({ isActive }) =>
              `app-nav-link ${isActive ? "app-nav-link-active" : ""}`
            }
          >
            Articles
          </NavLink>
        </nav>
        <main className="app-main">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/articles" element={<ArticlesPage />} />
            <Route path="/articles/:id" element={<ArticleDetailPage />} />
            <Route path="/events/:id" element={<EventDetailPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}

function NotFound() {
  return (
    <div className="placeholder-page">
      <h2>Not found</h2>
      <Link to="/articles">Go to articles</Link>
    </div>
  );
}
