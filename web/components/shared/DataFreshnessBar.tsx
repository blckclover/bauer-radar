import { Clock, Database } from "lucide-react";

import { cn } from "@/lib/utils";

export type DataSourceKind = "live" | "cache" | "mock" | "offline";

interface DataFreshnessBarProps {
  dataSource: DataSourceKind | string;
  updatedAt?: string | Date | null;
  sourceLabel?: string;
  className?: string;
}

const SOURCE_LABELS: Record<string, string> = {
  live: "Live API",
  cache: "API Cache",
  mock: "Mock Fallback",
  offline: "Offline",
};

function formatTimestamp(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function DataFreshnessBar({
  dataSource,
  updatedAt,
  sourceLabel,
  className,
}: DataFreshnessBarProps) {
  const label = sourceLabel ?? SOURCE_LABELS[dataSource] ?? dataSource;
  const isStale = dataSource === "mock" || dataSource === "offline";

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground",
        className
      )}
    >
      <span className="inline-flex items-center gap-1.5">
        <Database className="h-3.5 w-3.5" />
        資料來源：
        <span
          className={cn(
            "font-medium",
            isStale ? "text-amber-400" : "text-emerald-400"
          )}
        >
          {label}
        </span>
      </span>
      {updatedAt ? (
        <span className="inline-flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" />
          最後更新：{formatTimestamp(updatedAt)}
        </span>
      ) : null}
    </div>
  );
}
