// Lightweight toast / notification system (req 2.9a).
//
// The API client throws ApiError on any non-2xx response; consumers feed those
// errors into the context here so the UI shows a corner-positioned banner
// instead of silently swallowing the failure. No third-party toast library —
// keeps the dependency tree minimal.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

export type ToastVariant = "error" | "success" | "info";

export interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  toasts: Toast[];
  notify: (message: string, variant?: ToastVariant) => void;
  dismiss: (id: number) => void;
  clear: () => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// Auto-dismiss interval. Errors stay slightly longer than info/success so the
// user has time to read them.
const AUTO_DISMISS_MS: Record<ToastVariant, number> = {
  error: 6000,
  success: 3500,
  info: 3500,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextIdRef = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback(
    (message: string, variant: ToastVariant = "info") => {
      const id = nextIdRef.current++;
      setToasts((prev) => [...prev, { id, message, variant }]);
    },
    [],
  );

  const clear = useCallback(() => setToasts([]), []);

  const value = useMemo<ToastContextValue>(
    () => ({ toasts, notify, dismiss, clear }),
    [toasts, notify, dismiss, clear],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastTray toasts={toasts} dismiss={dismiss} />
    </ToastContext.Provider>
  );
}

/** Hook that returns the active toast context. */
export function useToasts(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToasts must be used inside <ToastProvider>");
  }
  return ctx;
}

function ToastTray({
  toasts,
  dismiss,
}: {
  toasts: Toast[];
  dismiss: (id: number) => void;
}) {
  return (
    <div
      className="toast-tray"
      role="region"
      aria-live="polite"
      aria-label="Notifications"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} dismiss={dismiss} />
      ))}
    </div>
  );
}

function ToastItem({
  toast,
  dismiss,
}: {
  toast: Toast;
  dismiss: (id: number) => void;
}) {
  useEffect(() => {
    const ms = AUTO_DISMISS_MS[toast.variant];
    const timer = setTimeout(() => dismiss(toast.id), ms);
    return () => clearTimeout(timer);
  }, [toast.id, toast.variant, dismiss]);

  return (
    <div className={`toast toast-${toast.variant}`} role="status">
      <span className="toast-message">{toast.message}</span>
      <button
        type="button"
        className="toast-dismiss"
        aria-label="Dismiss notification"
        onClick={() => dismiss(toast.id)}
      >
        ×
      </button>
    </div>
  );
}
