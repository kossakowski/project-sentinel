import { Link, Navigate, Route, Routes, useParams } from "react-router-dom";

import { ArticlesPage } from "./pages/ArticlesPage";
import { ToastProvider } from "./components/Toast";

/**
 * Root component. Phase 2 only ships the articles list page; the detail page
 * placeholder exists so the row-title links (req 2.2c) resolve to a real
 * route. Phase 3 will replace the placeholder with the full classifier view.
 */
export function App() {
  return (
    <ToastProvider>
      <div className="app-shell">
        <nav className="app-nav">
          <Link to="/articles" className="app-nav-link">
            Articles
          </Link>
        </nav>
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/articles" replace />} />
            <Route path="/articles" element={<ArticlesPage />} />
            <Route path="/articles/:id" element={<ArticleDetailPlaceholder />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}

function ArticleDetailPlaceholder() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="placeholder-page" data-testid="article-detail-placeholder">
      <h2>Article detail (Phase 3)</h2>
      <p>
        Article <code>{id}</code> — the full classifier-input view ships in Phase 3.
      </p>
      <Link to="/articles">← Back to articles</Link>
    </div>
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
