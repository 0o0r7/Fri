import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

export function PageShell({
  title,
  subtitle,
  children,
  maxWidth = "max-w-4xl",
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  maxWidth?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="relative min-h-dvh bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />
      <main className="relative z-10 mx-auto w-full flex-1 px-4 py-8 sm:px-6 sm:py-12">
        <div className={maxWidth}>
          <a
            href="#"
            className="mb-6 inline-flex items-center gap-1.5 font-mono text-xs text-muted transition-colors hover:text-accent"
          >
            <ArrowLeft className="size-3.5" />
            {t("common.backToHome")}
          </a>
          <h1 className="text-2xl font-bold tracking-tight text-accent sm:text-3xl">
            {title}
          </h1>
          <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
            {subtitle}
          </p>
          <div className="mt-8">{children}</div>
        </div>
      </main>
    </div>
  );
}

export function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 font-mono text-sm font-bold tracking-wide text-accent uppercase">
        {title}
      </h2>
      <div className="space-y-3 text-sm leading-relaxed text-muted sm:text-base">
        {children}
      </div>
    </section>
  );
}

export function Prose({ children }: { children: ReactNode }) {
  return <p className="text-pretty">{children}</p>;
}

export function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="my-3 overflow-x-auto rounded-lg border border-border bg-surface p-4 font-mono text-xs text-accent-2">
      <code>{children}</code>
    </pre>
  );
}

export function BulletList({ items }: { items: string[] | string }) {
  const list = typeof items === "string" ? items.split("\n").filter(Boolean) : items;
  return (
    <ul className="space-y-1.5 pl-1">
      {list.map((item, i) => (
        <li key={i} className="flex gap-2 text-pretty">
          <span className="mt-1.5 size-1 shrink-0 rounded-full bg-accent" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}
