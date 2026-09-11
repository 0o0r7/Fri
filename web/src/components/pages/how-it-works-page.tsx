import { useTranslation } from "react-i18next";
import { PageShell, Section, Prose } from "./page-shell";

export function HowItWorksPage() {
  const { t } = useTranslation();
  return (
    <PageShell title={t("howItWorks.title")} subtitle={t("howItWorks.subtitle")}>
      <Section title={t("howItWorks.pipelineTitle")}>
        <div className="space-y-4">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <div key={n} className="flop-card p-4">
              <h3 className="mb-1.5 font-mono text-sm font-bold text-fg">
                {t(`howItWorks.step${n}Title`)}
              </h3>
              <p className="text-sm text-pretty text-muted">
                {t(`howItWorks.step${n}Body`)}
              </p>
            </div>
          ))}
        </div>
      </Section>
      <Section title={t("howItWorks.scoringTitle")}>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="flop-card p-4">
            <p className="font-mono text-sm font-bold text-accent">
              {t("howItWorks.activityWeight")}
            </p>
            <p className="mt-1.5 text-xs text-pretty text-muted">
              {t("howItWorks.activityDesc")}
            </p>
          </div>
          <div className="flop-card p-4">
            <p className="font-mono text-sm font-bold text-good">
              {t("howItWorks.workWeight")}
            </p>
            <p className="mt-1.5 text-xs text-pretty text-muted">
              {t("howItWorks.workDesc")}
            </p>
          </div>
          <div className="flop-card p-4">
            <p className="font-mono text-sm font-bold text-mid">
              {t("howItWorks.reliabilityWeight")}
            </p>
            <p className="mt-1.5 text-xs text-pretty text-muted">
              {t("howItWorks.reliabilityDesc")}
            </p>
          </div>
        </div>
      </Section>
    </PageShell>
  );
}
