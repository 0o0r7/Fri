export function IndexPageSkeleton() {
  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />
      {/* Nav skeleton */}
      <header className="relative z-10 border-b border-border bg-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="size-9 animate-pulse rounded bg-elevated" />
            <div>
              <div className="h-3 w-10 animate-pulse rounded bg-elevated" />
              <div className="mt-1 h-3 w-32 animate-pulse rounded bg-elevated" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-8 w-56 animate-pulse rounded border border-border bg-surface lg:w-72" />
            <div className="flex h-8 gap-0 rounded border border-border bg-surface p-0">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-8 w-16 animate-pulse bg-elevated/60" />
              ))}
            </div>
          </div>
        </div>
      </header>

      {/* Ticker skeleton */}
      <div className="relative z-10 border-b border-border bg-surface/85">
        <div className="mx-auto flex max-w-screen-2xl items-center gap-3 px-4 py-1.5 sm:px-6">
          <div className="h-3 w-12 animate-pulse rounded bg-elevated" />
          <div className="h-3 w-20 animate-pulse rounded bg-elevated" />
          <div className="h-3 w-full max-w-md animate-pulse rounded bg-elevated/50" />
        </div>
      </div>

      {/* Stat band skeleton */}
      <section className="relative z-10 border-b border-border bg-surface/40">
        <div className="mx-auto max-w-screen-2xl px-4 py-3 sm:px-6">
          <div className="flop-metrics">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="px-4 py-3">
                <div className="h-2.5 w-12 animate-pulse rounded bg-elevated" />
                <div className="mt-2 h-4 w-16 animate-pulse rounded bg-elevated/70" />
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Main list/detail skeleton */}
      <div className="relative z-10 mx-auto grid min-h-0 w-full max-w-screen-2xl flex-1 grid-cols-1 lg:grid-cols-12">
        <div className="flex flex-col gap-2 px-4 py-3 sm:px-5 lg:col-span-5 lg:border-r lg:border-border">
          <div className="h-10 w-full animate-pulse rounded border border-border bg-surface" />
          <div className="flex gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-8 w-16 animate-pulse rounded border border-border bg-surface"
              />
            ))}
          </div>
          <div className="mt-2 space-y-1">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-12 w-full animate-pulse rounded bg-elevated/50"
              />
            ))}
          </div>
        </div>
        <aside className="hidden lg:col-span-7 lg:block">
          <div className="space-y-4 px-6 py-6 xl:px-8">
            <div className="h-5 w-32 animate-pulse rounded bg-elevated" />
            <div className="h-24 w-full animate-pulse rounded bg-elevated/50" />
            <div className="h-5 w-40 animate-pulse rounded bg-elevated" />
            <div className="h-48 w-full animate-pulse rounded bg-elevated/50" />
          </div>
        </aside>
      </div>
    </div>
  );
}
