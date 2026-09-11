import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageShell } from "./page-shell";
import { cn } from "@/lib/utils";

const CATEGORIES = ["general", "reputation", "data", "technical"] as const;

export function FaqPage() {
  const { t } = useTranslation();
  const [open, setOpen] = useState<string | null>("general-0");

  return (
    <PageShell title={t("faq.title")} subtitle={t("faq.subtitle")}>
      <div className="space-y-8">
        {CATEGORIES.map((cat) => {
          const questionCount = cat === "reputation" ? 5 : 4;
          return (
            <section key={cat}>
              <h2 className="mb-4 font-mono text-sm font-bold tracking-wide text-accent uppercase">
                {t(`faq.${cat}.title`)}
              </h2>
              <div className="space-y-2">
                {Array.from({ length: questionCount }, (_, i) => {
                  const key = `${cat}-${i}`;
                  const isOpen = open === key;
                  return (
                    <div key={key} className="flop-card overflow-hidden">
                      <button
                        type="button"
                        onClick={() => setOpen(isOpen ? null : key)}
                        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                      >
                        <span className="text-sm font-medium text-fg">
                          {t(`faq.${cat}.q${i + 1}`)}
                        </span>
                        <ChevronDown
                          className={cn(
                            "size-4 shrink-0 text-muted transition-transform",
                            isOpen && "rotate-180",
                          )}
                        />
                      </button>
                      {isOpen && (
                        <div className="px-4 pb-3 text-sm text-pretty text-muted">
                          {t(`faq.${cat}.a${i + 1}`)}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </PageShell>
  );
}
