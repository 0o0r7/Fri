export function IndexPageSkeleton() {
  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />
      <header className="relative z-10 border-b border-border">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="size-9 animate-pulse rounded-lg bg-elevated" />
            <div>
              <div className="h-3 w-10 animate-pulse rounded bg-elevated" />
              <div className="mt-1 h-4 w-44 animate-pulse rounded bg-elevated" />
            </div>
          </div>
          <div className="flex gap-2">
            <div className="h-9 w-20 animate-pulse rounded-md bg-elevated" />
            <div className="h-9 w-20 animate-pulse rounded-md bg-elevated" />
            <div className="h-9 w-16 animate-pulse rounded-md bg-elevated" />
          </div>
        </div>
      </header>
      <div className="relative z-10 mx-auto grid min-h-0 w-full max-w-screen-2xl flex-1 grid-cols-1 lg:grid-cols-12">
        <div className="flex flex-col gap-2 px-4 py-3 sm:px-5 lg:col-span-5 lg:border-r lg:border-border">
          <div className="h-10 w-full animate-pulse rounded-md bg-elevated" />
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-12 w-full animate-pulse rounded-lg bg-elevated/50"
              />
            ))}
          </div>
        </div>
        <aside className="hidden lg:col-span-7 lg:block">
          <div className="space-y-4 px-6 py-6 xl:px-8">
            <div className="h-6 w-32 animate-pulse rounded bg-elevated" />
            <div className="h-24 w-full animate-pulse rounded-lg bg-elevated/50" />
            <div className="h-6 w-40 animate-pulse rounded bg-elevated" />
            <div className="h-48 w-full animate-pulse rounded-lg bg-elevated/50" />
          </div>
        </aside>
      </div>
    </div>
  );
}
