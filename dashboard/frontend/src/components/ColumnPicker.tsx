import { useEffect, useRef, useState } from "react";

import { ALL_COLUMNS, type ColumnKey } from "./columns";

interface ColumnPickerProps {
  visible: ReadonlyArray<ColumnKey>;
  onToggle: (key: ColumnKey) => void;
}

/**
 * Dropdown / popover for toggling table column visibility (req 2.3).
 * The visibility state itself is owned by the parent (so it can be persisted
 * to localStorage); this component just renders the checkbox list and a
 * trigger button.
 */
export function ColumnPicker({ visible, onToggle }: ColumnPickerProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click so the popover behaves like a native dropdown.
  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(event: MouseEvent) {
      if (!rootRef.current) return;
      const target = event.target as Node | null;
      if (target && !rootRef.current.contains(target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  const visibleSet = new Set(visible);

  return (
    <div className="column-picker" ref={rootRef}>
      <button
        type="button"
        className="column-picker-trigger"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        Columns
      </button>
      {open && (
        <div className="column-picker-popover" role="menu">
          <p className="column-picker-heading">Visible columns</p>
          <ul className="column-picker-list">
            {ALL_COLUMNS.map((col) => {
              const checked = visibleSet.has(col.key);
              return (
                <li key={col.key}>
                  <label className="column-picker-item">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggle(col.key)}
                      aria-label={`Toggle column ${col.label}`}
                    />
                    <span>{col.label}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
