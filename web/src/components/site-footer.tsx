import { useTranslation } from "react-i18next";
import { FriMark } from "@/components/logo";
import { LanguageSelector } from "@/components/language-selector";

export function SiteFooter() {
  const { t } = useTranslation();
  return (
    <footer className="relative z-10 border-t border-border bg-bg">
      <div className="mx-auto max-w-screen-2xl px-4 py-10 sm:px-6">
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-3 lg:grid-cols-5">
          {/* Brand column */}
          <div className="col-span-2 sm:col-span-3 lg:col-span-2">
            <div className="flex items-center gap-2.5">
              <FriMark />
              <div className="text-left leading-tight">
                <p className="font-mono text-sm font-bold tracking-[0.18em] text-accent">FRI</p>
                <p className="font-mono text-[11px] tracking-wide text-muted">
                  flop reputation index
                </p>
              </div>
            </div>
            <p className="mt-3 max-w-xs text-sm text-pretty text-muted">
              {t("footer.tagline")}
            </p>
            <p className="mt-2 text-xs text-faint">
              {t("common.independentTool")}
            </p>
            <div className="mt-4">
              <LanguageSelector />
            </div>
          </div>

          {/* Product column */}
          <div>
            <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
              {t("footer.product")}
            </h3>
            <ul className="space-y-2">
              <li><FooterLink href="#about" label={t("footer.about")} /></li>
              <li><FooterLink href="#how-it-works" label={t("footer.howItWorks")} /></li>
              <li><FooterLink href="#faq" label={t("footer.faq")} /></li>
            </ul>
          </div>

          {/* Resources column */}
          <div>
            <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
              {t("footer.resources")}
            </h3>
            <ul className="space-y-2">
              <li><FooterLink href="#docs" label={t("footer.docs")} /></li>
              <li><FooterLink href="#docs" label={t("footer.dataMethodology")} /></li>
            </ul>
          </div>

          {/* Legal column */}
          <div>
            <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
              {t("footer.legal")}
            </h3>
            <ul className="space-y-2">
              <li><FooterLink href="#privacy" label={t("footer.privacy")} /></li>
              <li><FooterLink href="#terms" label={t("footer.terms")} /></li>
            </ul>
          </div>
        </div>

        <div className="mt-8 flex flex-col items-center justify-between gap-2 border-t border-border pt-6 sm:flex-row">
          <p className="font-mono text-xs text-faint">
            © {new Date().getFullYear()} FRI — {t("common.independentTool")}
          </p>
          <p className="font-mono text-xs text-faint">
            Built with FastAPI · React · SSE
          </p>
        </div>
      </div>
    </footer>
  );
}

function FooterLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="text-sm text-muted transition-colors hover:text-accent"
    >
      {label}
    </a>
  );
}
