import { useState, useRef, useEffect } from "react";
import { Globe, Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SUPPORTED_LOCALES, applyDirection } from "@/i18n";
import { cn } from "@/lib/utils";

export function LanguageSelector({ compact = false }: { compact?: boolean }) {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const current = SUPPORTED_LOCALES.find((l) => l.code === i18n.language) ?? SUPPORTED_LOCALES[0];

  function select(code: string) {
    i18n.changeLanguage(code);
    localStorage.setItem("fri-lang", code);
    applyDirection(code);
    setOpen(false);
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded border border-border bg-surface px-2.5 font-mono text-xs text-muted transition-colors hover:border-accent hover:text-fg",
          open && "border-accent text-fg",
        )}
        aria-label={t("common.language")}
      >
        <Globe className="size-3.5" />
        {compact ? <span>{current.flag}</span> : <span>{current.label}</span>}
      </button>
      {open && (
        <div className="absolute bottom-full right-0 mb-1 w-44 overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
          {SUPPORTED_LOCALES.map((l) => (
            <button
              key={l.code}
              type="button"
              onClick={() => select(l.code)}
              className={cn(
                "flex w-full items-center justify-between px-3 py-2 font-mono text-xs transition-colors hover:bg-elevated",
                l.code === i18n.language ? "text-accent" : "text-muted",
              )}
            >
              <span className="flex items-center gap-2">
                <span>{l.flag}</span>
                {l.label}
              </span>
              {l.code === i18n.language && <Check className="size-3.5" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
