import { useRef, useState } from "react";
import { Popover } from "./Popover";
import { THEME_LABELS, THEME_NAMES, type ThemeName } from "../theme/theme";

interface ThemePickerProps {
  theme: ThemeName;
  onSelect: (theme: ThemeName) => void;
}

/**
 * #5298 — theme switcher.
 *
 * The operational product exposes the same five themes in the settings dialog
 * (`data-theme-value` buttons). The clone keeps the same theme names and the
 * same `data-theme` attribute contract, and puts the switcher in the top bar
 * so the theme change can be observed without opening a dialog.
 */
export function ThemePicker({ theme, onSelect }: ThemePickerProps) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement | null>(null);

  return (
    <div className="clone-topbar-anchor" ref={anchorRef}>
      <button
        type="button"
        className="clone-topbar-button"
        id="themePickerButton"
        aria-haspopup="true"
        aria-expanded={open ? "true" : "false"}
        aria-controls="cloneThemePicker"
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">◐</span>
        <span>테마</span>
      </button>
      {open ? (
        <Popover anchorRef={anchorRef} align="end" onClose={() => setOpen(false)}>
          <div id="cloneThemePicker" role="group" aria-label="테마 선택">
            {THEME_NAMES.map((name) => (
              <button
                key={name}
                type="button"
                className="clone-theme-option"
                data-theme-value={name}
                aria-pressed={theme === name ? "true" : "false"}
                onClick={() => {
                  onSelect(name);
                  setOpen(false);
                }}
              >
                {THEME_LABELS[name]}
              </button>
            ))}
          </div>
        </Popover>
      ) : null}
    </div>
  );
}
