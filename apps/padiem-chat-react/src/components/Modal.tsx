import { useEffect, useRef, type ReactNode } from "react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  id?: string;
  className?: string;
  labelledBy: string;
  describedBy?: string;
  children: ReactNode;
}

/**
 * #5298 — the modal surface.
 *
 * The product's dialogs are native `<dialog>` elements, so the browser owns
 * the focus trap, the Escape key and the inert background. The clone uses the
 * same element and the same `showModal()` call, and it returns the focus to
 * the trigger when the dialog closes.
 */
export function Modal({
  open,
  onClose,
  id,
  className,
  labelledBy,
  describedBy,
  children,
}: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!open) return;
    if (!dialog.open) {
      returnFocusRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (typeof dialog.showModal === "function") {
        try {
          dialog.showModal();
        } catch {
          dialog.setAttribute("open", "");
        }
      } else {
        dialog.setAttribute("open", "");
      }
    }
    // Closing — either the state changed or the surface unmounted — returns the
    // focus to the trigger.
    return () => {
      if (dialog.open) {
        if (typeof dialog.close === "function") {
          dialog.close();
        } else {
          dialog.removeAttribute("open");
        }
      }
      const trigger = returnFocusRef.current;
      if (trigger && trigger.isConnected) {
        trigger.focus();
      }
      returnFocusRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // The native dialog answers Escape on its own, and the `cancel` handler
      // below covers the browsers that do not. Closing is idempotent, so both
      // paths are safe.
      onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      id={id}
      className={className}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={onClose}
    >
      {children}
    </dialog>
  );
}
