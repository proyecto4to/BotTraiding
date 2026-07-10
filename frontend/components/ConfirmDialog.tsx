"use client";

/** Blocking confirmation dialog used for dangerous actions (circuit-breaker
 * reset, Demo/Real mode switch). Pure display; the caller performs the
 * action only after explicit confirmation. */

import type { ReactNode } from "react";

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  danger = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal">
        <h3 className="modal-title">{title}</h3>
        <div className="modal-body">{body}</div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className={danger ? "btn btn-danger" : "btn btn-primary"}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
