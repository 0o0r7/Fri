import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PageShell, Section, Prose, CodeBlock, BulletList } from "./page-shell";
import { cn } from "@/lib/utils";

const SECTIONS = [
  "overview",
  "dataSources",
  "algorithm",
  "kibble",
  "tclk",
  "api",
] as const;

export function DocsPage() {
  const { t } = useTranslation();
  const [active, setActive] = useState<(typeof SECTIONS)[number]>("overview");

  return (
    <PageShell
      title={t("docs.title")}
      subtitle={t("docs.subtitle")}
      maxWidth="max-w-5xl"
    >
      <div className="flex gap-8">
        {/* Sidebar TOC */}
        <aside className="sticky top-20 hidden h-fit w-48 shrink-0 lg:block">
          <nav className="flex flex-col gap-1">
            {SECTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => {
                  setActive(s);
                  document.getElementById(`docs-${s}`)?.scrollIntoView({ behavior: "smooth" });
                }}
                className={cn(
                  "rounded px-3 py-1.5 text-left font-mono text-xs transition-colors",
                  active === s
                    ? "bg-accent/10 text-accent"
                    : "text-muted hover:bg-surface hover:text-fg",
                )}
              >
                {t(`docs.toc.${s}`)}
              </button>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <div className="min-w-0 flex-1 space-y-10">
          <section id="docs-overview" className="scroll-mt-20">
            <h2 className="mb-3 flop-section-heading text-lg">{t("docs.overview.title")}</h2>
            <div className="space-y-3 text-sm text-muted">
              <Prose>{t("docs.overview.body")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.overview.architectureTitle")}</h3>
              <Prose>{t("docs.overview.architectureBody")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.overview.dataFlowTitle")}</h3>
              <Prose>{t("docs.overview.dataFlowBody")}</Prose>
            </div>
          </section>

          <section id="docs-dataSources" className="scroll-mt-20">
            <h2 className="mb-3 flop-section-heading text-lg">{t("docs.dataSources.title")}</h2>
            <div className="space-y-3 text-sm text-muted">
              <Prose>{t("docs.dataSources.intro")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.dataSources.roomsTitle")}</h3>
              <Prose>{t("docs.dataSources.roomsBody")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.dataSources.kibbleTitle")}</h3>
              <Prose>{t("docs.dataSources.kibbleBody")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.dataSources.tclkTitle")}</h3>
              <Prose>{t("docs.dataSources.tclkBody")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.dataSources.freshnessTitle")}</h3>
              <Prose>{t("docs.dataSources.freshnessBody")}</Prose>
            </div>
          </section>

          <section id="docs-algorithm" className="scroll-mt-20">
            <h2 className="mb-3 flop-section-heading text-lg">{t("docs.algorithm.title")}</h2>
            <div className="space-y-3 text-sm text-muted">
              <Prose>{t("docs.algorithm.formulaBody")}</Prose>
              <CodeBlock>{t("docs.algorithm.formula")}</CodeBlock>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.algorithm.activityTitle")}</h3>
              <Prose>{t("docs.algorithm.activityBody")}</Prose>
              <BulletList items={t("docs.algorithm.activityMetrics", { returnObjects: true }) as string[]} />
              <CodeBlock>{t("docs.algorithm.activityFormula")}</CodeBlock>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.algorithm.workTitle")}</h3>
              <Prose>{t("docs.algorithm.workBody")}</Prose>
              <BulletList items={t("docs.algorithm.workMetrics", { returnObjects: true }) as string[]} />
              <CodeBlock>{t("docs.algorithm.workFormula")}</CodeBlock>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.algorithm.reliabilityTitle")}</h3>
              <Prose>{t("docs.algorithm.reliabilityBody")}</Prose>
              <BulletList items={t("docs.algorithm.reliabilityMetrics", { returnObjects: true }) as string[]} />
              <CodeBlock>{t("docs.algorithm.reliabilityFormula")}</CodeBlock>
              <p className="text-xs text-faint">{t("docs.algorithm.reliabilityNote")}</p>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.algorithm.bandsTitle")}</h3>
              <Prose>{t("docs.algorithm.bandsBody")}</Prose>
              <BulletList items={[
                t("docs.algorithm.bandHigh"),
                t("docs.algorithm.bandMid"),
                t("docs.algorithm.bandLow"),
              ]} />
            </div>
          </section>

          <section id="docs-kibble" className="scroll-mt-20">
            <h2 className="mb-3 flop-section-heading text-lg">{t("docs.kibble.title")}</h2>
            <div className="space-y-3 text-sm text-muted">
              <Prose>{t("docs.kibble.intro")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.kibble.lifecycleTitle")}</h3>
              <Prose>{t("docs.kibble.lifecycleBody")}</Prose>
              <CodeBlock>{t("docs.kibble.states")}</CodeBlock>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.kibble.rolesTitle")}</h3>
              <Prose>{t("docs.kibble.rolesBody")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.kibble.scoringTitle")}</h3>
              <Prose>{t("docs.kibble.scoringBody")}</Prose>
            </div>
          </section>

          <section id="docs-tclk" className="scroll-mt-20">
            <h2 className="mb-3 flop-section-heading text-lg">{t("docs.tclk.title")}</h2>
            <div className="space-y-3 text-sm text-muted">
              <Prose>{t("docs.tclk.intro")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.tclk.lifecycleTitle")}</h3>
              <Prose>{t("docs.tclk.lifecycleBody")}</Prose>
              <CodeBlock>{t("docs.tclk.states")}</CodeBlock>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.tclk.rolesTitle")}</h3>
              <Prose>{t("docs.tclk.rolesBody")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.tclk.scoringTitle")}</h3>
              <Prose>{t("docs.tclk.scoringBody")}</Prose>
            </div>
          </section>

          <section id="docs-api" className="scroll-mt-20">
            <h2 className="mb-3 flop-section-heading text-lg">{t("docs.api.title")}</h2>
            <div className="space-y-3 text-sm text-muted">
              <Prose>{t("docs.api.intro")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.api.baseUrl")}</h3>
              <CodeBlock>https://&lt;fri-domain&gt;/api</CodeBlock>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.api.endpointsTitle")}</h3>
              <BulletList items={[
                t("docs.api.ep1"), t("docs.api.ep2"), t("docs.api.ep3"), t("docs.api.ep4"),
                t("docs.api.ep5"), t("docs.api.ep6"), t("docs.api.ep7"), t("docs.api.ep8"),
              ]} />
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.api.rateLimitTitle")}</h3>
              <Prose>{t("docs.api.rateLimitBody")}</Prose>
              <h3 className="pt-2 font-mono text-sm font-bold text-fg">{t("docs.api.disclaimerTitle")}</h3>
              <Prose>{t("docs.api.disclaimerBody")}</Prose>
            </div>
          </section>
        </div>
      </div>
    </PageShell>
  );
}
