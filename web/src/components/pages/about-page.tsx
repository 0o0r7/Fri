import { useTranslation } from "react-i18next";
import { PageShell, Section, Prose } from "./page-shell";

export function AboutPage() {
  const { t } = useTranslation();
  return (
    <PageShell title={t("about.title")} subtitle={t("about.subtitle")}>
      <Section title={t("about.whatIsTitle")}>
        <Prose>{t("about.whatIsBody")}</Prose>
      </Section>
      <Section title={t("about.whyExistsTitle")}>
        <Prose>{t("about.whyExistsBody")}</Prose>
      </Section>
      <Section title={t("about.whatProblemTitle")}>
        <Prose>{t("about.whatProblemBody")}</Prose>
      </Section>
      <Section title={t("about.howDifferentTitle")}>
        <Prose>{t("about.howDifferentBody")}</Prose>
      </Section>
      <div className="mt-10 flex flex-col gap-3 border-t border-border pt-6 sm:flex-row">
        <a
          href="#reputation"
          className="inline-flex h-10 items-center justify-center rounded-md bg-accent px-5 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
        >
          {t("about.ctaReputation")}
        </a>
        <a
          href="#how-it-works"
          className="inline-flex h-10 items-center justify-center rounded-md border border-border bg-surface px-5 text-sm text-fg transition-colors hover:border-accent"
        >
          {t("about.ctaHowItWorks")}
        </a>
      </div>
    </PageShell>
  );
}
