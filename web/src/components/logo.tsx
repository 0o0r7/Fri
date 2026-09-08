import { cn } from "@/lib/utils";

export function FriMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-9 items-end justify-center gap-0.5 rounded-lg bg-elevated pb-1.5 shadow-[var(--shadow-border)]",
        className,
      )}
      aria-hidden="true"
    >
      <span className="h-1.5 w-1 rounded-sm bg-accent/45" />
      <span className="h-2.5 w-1 rounded-sm bg-accent/70" />
      <span className="h-3.5 w-1 rounded-sm bg-accent" />
      <span className="h-4.5 w-1 rounded-sm bg-good" />
    </span>
  );
}
