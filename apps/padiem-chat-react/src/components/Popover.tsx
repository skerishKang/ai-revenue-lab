import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

interface PopoverProps {
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  align?: "start" | "end";
  className?: string;
  children: ReactNode;
}

/**
 * #5298 — anchored popover.
 *
 * The operational stylesheets give the top bar and the conversation panel the
 * same stacking level, so a dropdown that lives inside the top bar cannot be
 * raised above the conversation. The popover is therefore rendered at the
 * document root and positioned from the anchor's own box, which keeps the
 * operational cascade untouched and the dropdown usable.
 */
export function Popover({
  anchorRef,
  onClose,
  align = "start",
  className = "",
  children,
}: PopoverProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [style, setStyle] = useState<CSSProperties>({ visibility: "hidden" });

  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    const place = () => {
      const rect = anchor.getBoundingClientRect();
      setStyle({
        position: "fixed",
        top: Math.round(rect.bottom + 6),
        left: align === "end" ? Math.round(rect.right) : Math.round(rect.left),
        transform: align === "end" ? "translateX(-100%)" : undefined,
        visibility: "visible",
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchorRef, align]);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (panelRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, anchorRef]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div ref={panelRef} className={`clone-popover ${className}`.trim()} style={style}>
      {children}
    </div>,
    document.body,
  );
}
