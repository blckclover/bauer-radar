"use client";

import { AlertCircle, HelpCircle, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ComponentStateProps } from "@/types";

export interface MetricCardProps extends ComponentStateProps {
  label: string;
  value: string;
  subtext?: string;
  tooltip?: string;
  tone?: "default" | "positive" | "negative" | "neutral";
}

const valueToneClasses = {
  default: "text-foreground",
  positive: "text-emerald-400",
  negative: "text-red-400",
  neutral: "text-slate-300",
};

export function MetricCard({
  label,
  value,
  subtext,
  tooltip,
  tone = "default",
  isLoading = false,
  error = null,
}: MetricCardProps) {
  if (error) {
    return (
      <Card className="border-destructive/30 bg-card/70">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </CardTitle>
          <AlertCircle className="h-4 w-4 text-destructive" />
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">{error}</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card className="border-border/60 bg-card/70">
        <CardHeader className="pb-2">
          <Skeleton className="h-3 w-20" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-7 w-16" />
          <Skeleton className="mt-2 h-3 w-24" />
        </CardContent>
      </Card>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <Card className="border-border/60 bg-card/70 transition-colors hover:border-border">
        <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
          <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {label}
          </CardTitle>
          {tooltip ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="rounded-full text-muted-foreground hover:text-foreground"
                  aria-label={`${label} 說明`}
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs">
                {tooltip}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-1">
          <div
            className={cn(
              "text-2xl font-bold tabular-nums",
              valueToneClasses[tone]
            )}
          >
            {value}
          </div>
          {subtext ? (
            <CardDescription className="text-xs">{subtext}</CardDescription>
          ) : null}
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}

export function MetricCardGrid({
  children,
  columns = 4,
}: {
  children: React.ReactNode;
  columns?: 2 | 3 | 4;
}) {
  const gridClass =
    columns === 2
      ? "grid-cols-1 sm:grid-cols-2"
      : columns === 3
        ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
        : "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4";

  return (
    <div className={cn("grid gap-4", gridClass)}>{children}</div>
  );
}
