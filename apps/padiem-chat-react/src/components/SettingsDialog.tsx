import { Modal } from "./Modal";
import { useLocale } from "../i18n/LocaleProvider";
import { THEME_LABELS, THEME_NAMES, type ThemeName } from "../theme/theme";
import type { LocaleCode } from "../lib/locale";

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
  theme: ThemeName;
  onSelectTheme: (theme: ThemeName) => void;
}

const LANGUAGES: { code: LocaleCode; label: string }[] = [
  { code: "ko", label: "KR" },
  { code: "en", label: "EN" },
];

/**
 * #5298 — the settings surface.
 *
 * The structure is the product's settings dialog: the same ids, the same
 * classes and the same `data-theme-value` / `data-locale-value` contracts, so
 * the approved styling and the product's own copy apply unchanged.
 */
export function SettingsDialog({
  open,
  onClose,
  theme,
  onSelectTheme,
}: SettingsDialogProps) {
  const { language, setLanguage, t } = useLocale();

  return (
    <Modal
      open={open}
      onClose={onClose}
      id="settingsDialog"
      className="settings-dialog"
      labelledBy="settingsTitle"
    >
      <form className="settings-panel" method="dialog" onSubmit={(event) => event.preventDefault()}>
        <div className="settings-header">
          <div>
            <p>{t("settings-kicker", null) || "Padiem Chat"}</p>
            <h2 id="settingsTitle">{t("settings") || "설정"}</h2>
          </div>
          <button
            className="settings-close"
            id="settingsCloseButton"
            type="button"
            aria-label={t("settings-close") || "설정 닫기"}
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <section className="settings-section" aria-labelledby="appearanceTitle">
          <p className="settings-label">{t("appearance") || "APPEARANCE"}</p>
          <h3 id="appearanceTitle">{t("theme") || "테마"}</h3>
          <div
            className="theme-picker"
            role="group"
            aria-label={t("theme-picker") || "테마 선택"}
            id="themePicker"
          >
            {THEME_NAMES.map((name) => (
              <button
                key={name}
                type="button"
                className="theme-option"
                data-theme-value={name}
                aria-pressed={theme === name ? "true" : "false"}
                onClick={() => onSelectTheme(name)}
              >
                {THEME_LABELS[name]}
              </button>
            ))}
          </div>
        </section>

        <section className="settings-section" aria-labelledby="languageTitle">
          <p className="settings-label">{t("language") || "LANGUAGE"}</p>
          <h3 id="languageTitle">{t("language-choice") || "언어"}</h3>
          <div
            className="language-picker"
            role="group"
            aria-label={t("language-picker") || "언어 선택"}
            id="languagePicker"
          >
            {LANGUAGES.map((entry) => (
              <button
                key={entry.code}
                type="button"
                className="language-option"
                data-locale-value={entry.code}
                aria-pressed={language === entry.code ? "true" : "false"}
                onClick={() => setLanguage(entry.code)}
              >
                {entry.label}
              </button>
            ))}
          </div>
        </section>

        <section className="settings-section settings-help" aria-labelledby="settingsHelpTitle">
          <p className="settings-label">HELP &amp; GUIDE</p>
          <h3 id="settingsHelpTitle">{t("settings-help-title") || "문서·사용 안내"}</h3>
          <details className="settings-guide" id="settingsExcelGuide">
            <summary>{t("settings-help-excel") || "Excel 원본 보관 방법"}</summary>
            <p>
              {t("settings-help-excel-description") ||
                "Claw의 Excel 파일 작업에서 파일을 선택하고 원본 보관을 누르세요."}
            </p>
          </details>
        </section>

        <div className="settings-footer">
          <button className="settings-done" id="settingsDoneButton" type="button" onClick={onClose}>
            {t("done") || "완료"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
