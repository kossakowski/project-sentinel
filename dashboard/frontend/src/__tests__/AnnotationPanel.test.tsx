// Tests for AnnotationPanel — covers acceptance test #10 (req 4.3a) plus
// requirement-coverage for 4.3 (form layout), 4.3b (save without leaving),
// and 4.3c (delete confirmation).

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import * as client from "../api/client";
import { ApiError } from "../api/client";
import { AnnotationPanel } from "../components/AnnotationPanel";
import { ToastProvider } from "../components/Toast";
import { makeAnnotation } from "./fixtures";

function renderPanel(opts: {
  articleId?: string;
  initialAnnotation?: ReturnType<typeof makeAnnotation> | null;
  confirmDelete?: (msg: string) => boolean;
} = {}) {
  const { articleId = "art-1", initialAnnotation, confirmDelete } = opts;
  return render(
    <ToastProvider>
      <AnnotationPanel
        articleId={articleId}
        initialAnnotation={initialAnnotation}
        confirmDelete={confirmDelete}
      />
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AnnotationPanel", () => {
  // covers test #10 (req 4.3a) — form pre-fills from an existing annotation.
  it("test_annotation_panel_prefill", () => {
    const existing = makeAnnotation({
      article_id: "art-1",
      label: "uncertain",
      expected_urgency: 7,
      notes: "Mixed signals from the source — wait for corroboration.",
      created_at: "2026-05-22T10:00:00+00:00",
      updated_at: "2026-05-22T11:30:00+00:00",
    });
    renderPanel({ initialAnnotation: existing });

    // Label button for "uncertain" is the selected radio.
    const uncertainButton = screen.getByTestId("annotation-panel-label-uncertain");
    expect(uncertainButton.getAttribute("aria-checked")).toBe("true");
    expect(uncertainButton.className).toMatch(/selected/);

    // The other two labels are not selected.
    expect(screen.getByTestId("annotation-panel-label-correct").getAttribute("aria-checked")).toBe(
      "false",
    );
    expect(screen.getByTestId("annotation-panel-label-incorrect").getAttribute("aria-checked")).toBe(
      "false",
    );

    // Urgency input shows the existing value.
    const urgencyInput = screen.getByTestId("annotation-panel-urgency") as HTMLInputElement;
    expect(urgencyInput.value).toBe("7");

    // Notes textarea shows the existing notes.
    const notesArea = screen.getByTestId("annotation-panel-notes") as HTMLTextAreaElement;
    expect(notesArea.value).toBe("Mixed signals from the source — wait for corroboration.");

    // "Last updated" timestamp visible (req 4.3a).
    const lastUpdated = screen.getByTestId("annotation-panel-updated");
    // updated_at (UTC 11:30 on May 22) → Europe/Warsaw is UTC+2 (CEST) → 13:30.
    expect(lastUpdated.textContent).toMatch(/2026-05-22 13:30/);

    // The save button label reads "Update annotation" when an annotation
    // already exists — small but pins the edit-vs-create UX state.
    const save = screen.getByTestId("annotation-panel-save");
    expect(save.textContent).toMatch(/Update annotation/);

    // Delete button is rendered when an annotation exists (req 4.3c).
    expect(screen.getByTestId("annotation-panel-delete")).toBeInTheDocument();
  });

  // covers req 4.3 — fresh state has default-empty form + no delete button.
  it("renders empty form when no annotation exists yet", () => {
    renderPanel({ initialAnnotation: null });

    // None of the labels are pre-selected... actually default is "correct"
    // because the form has to start on something; assert that explicitly.
    expect(screen.getByTestId("annotation-panel-label-correct").getAttribute("aria-checked")).toBe(
      "true",
    );
    expect((screen.getByTestId("annotation-panel-urgency") as HTMLInputElement).value).toBe("");
    expect((screen.getByTestId("annotation-panel-notes") as HTMLTextAreaElement).value).toBe("");

    // "Last updated" line absent.
    expect(screen.queryByTestId("annotation-panel-updated")).not.toBeInTheDocument();

    // Save button reads "Save annotation"; Delete button NOT rendered (req 4.3c).
    expect(screen.getByTestId("annotation-panel-save").textContent).toMatch(/Save annotation/);
    expect(screen.queryByTestId("annotation-panel-delete")).not.toBeInTheDocument();
  });

  // covers req 4.3b — submitting POSTs and the form stays on screen.
  it("submits the form and shows a success indicator without navigating away", async () => {
    const saveSpy = vi.spyOn(client, "saveAnnotation").mockResolvedValue(
      makeAnnotation({
        article_id: "art-1",
        label: "incorrect",
        expected_urgency: 9,
        notes: "Mislabelled — should be drone_attack.",
        updated_at: "2026-05-22T12:00:00+00:00",
      }),
    );

    const user = userEvent.setup();
    renderPanel({ initialAnnotation: null });

    await user.click(screen.getByTestId("annotation-panel-label-incorrect"));
    await user.clear(screen.getByTestId("annotation-panel-urgency"));
    await user.type(screen.getByTestId("annotation-panel-urgency"), "9");
    await user.clear(screen.getByTestId("annotation-panel-notes"));
    await user.type(
      screen.getByTestId("annotation-panel-notes"),
      "Mislabelled — should be drone_attack.",
    );

    await user.click(screen.getByTestId("annotation-panel-save"));

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });
    expect(saveSpy).toHaveBeenCalledWith({
      article_id: "art-1",
      label: "incorrect",
      expected_urgency: 9,
      notes: "Mislabelled — should be drone_attack.",
    });

    // Success indicator appears (req 4.3b).
    await waitFor(() => {
      expect(screen.getByTestId("annotation-panel-success")).toBeInTheDocument();
    });

    // The form stays mounted (req 4.3b — "remain on screen, no navigation").
    expect(screen.getByTestId("annotation-panel-form")).toBeInTheDocument();
    // And it now shows the post-save state: delete button + "Update" label.
    expect(screen.getByTestId("annotation-panel-delete")).toBeInTheDocument();
    expect(screen.getByTestId("annotation-panel-save").textContent).toMatch(/Update annotation/);
  });

  // covers req 4.3 — client-side urgency validation catches bad input
  // before round-tripping to the backend.
  it("rejects out-of-range urgency client-side without calling the API", async () => {
    const saveSpy = vi.spyOn(client, "saveAnnotation");
    const user = userEvent.setup();
    renderPanel({ initialAnnotation: null });

    await user.clear(screen.getByTestId("annotation-panel-urgency"));
    await user.type(screen.getByTestId("annotation-panel-urgency"), "11");
    await user.click(screen.getByTestId("annotation-panel-save"));

    await waitFor(() => {
      expect(screen.getByTestId("annotation-panel-local-error")).toBeInTheDocument();
    });
    expect(saveSpy).not.toHaveBeenCalled();
  });

  // covers req 4.3c — Delete button confirms before deleting.
  it("confirms before deleting and calls deleteAnnotation only on OK", async () => {
    const deleteSpy = vi.spyOn(client, "deleteAnnotation").mockResolvedValue();
    const user = userEvent.setup();
    // Confirm rejected first → no delete.
    const confirmRejected = vi.fn(() => false);
    const { unmount } = renderPanel({
      initialAnnotation: makeAnnotation({ article_id: "art-1" }),
      confirmDelete: confirmRejected,
    });
    await user.click(screen.getByTestId("annotation-panel-delete"));
    expect(confirmRejected).toHaveBeenCalledTimes(1);
    expect(deleteSpy).not.toHaveBeenCalled();
    unmount();

    // Confirm accepted second → delete fires.
    const confirmAccepted = vi.fn(() => true);
    renderPanel({
      initialAnnotation: makeAnnotation({ article_id: "art-1" }),
      confirmDelete: confirmAccepted,
    });
    await user.click(screen.getByTestId("annotation-panel-delete"));
    expect(confirmAccepted).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("art-1");
    });

    // After delete: form returns to the empty / create state.
    await waitFor(() => {
      expect(screen.queryByTestId("annotation-panel-delete")).not.toBeInTheDocument();
    });
  });

  // covers req 4.3 — server error surfaces in the panel (and via toast).
  it("surfaces save errors instead of silently swallowing them", async () => {
    vi.spyOn(client, "saveAnnotation").mockRejectedValue(
      new ApiError("400 Invalid label", 400, { error: "Invalid label" }, "/api/annotations"),
    );

    const user = userEvent.setup();
    renderPanel({ initialAnnotation: null });
    await user.click(screen.getByTestId("annotation-panel-save"));

    await waitFor(() => {
      expect(screen.getByTestId("annotation-panel-server-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("annotation-panel-server-error").textContent).toMatch(
      /Invalid label/,
    );
  });
});
