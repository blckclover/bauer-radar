"use client";

import { AlertTriangle, Info, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ComponentStateProps, RedTeamFinding, RedTeamSeverity } from "@/types";

export interface RedTeamAlertProps extends ComponentStateProps {
  findings: RedTeamFinding[];
  title?: string;
}

const severityConfig: Record<
  RedTeamSeverity,
  {
    label: string;
    badgeVariant: "destructive" | "warning" | "secondary";
    icon: typeof ShieldAlert;
    borderClass: string;
    bgClass: string;
  }
> = {
  critical: {
    label: "致命",
    badgeVariant: "destructive",
    icon: ShieldAlert,
    borderClass: "border-red-500/40",
    bgClass: "bg-red-500/5",
  },
  warning: {
    label: "警告",
    badgeVariant: "warning",
    icon: AlertTriangle,
    borderClass: "border-amber-500/40",
    bgClass: "bg-amber-500/5",
  },
  info: {
    label: "提示",
    badgeVariant: "secondary",
    icon: Info,
    borderClass: "border-slate-500/40",
    bgClass: "bg-slate-500/5",
  },
};

function FindingItem({ finding }: { finding: RedTeamFinding }) {
  const config = severityConfig[finding.severity];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        config.borderClass,
        config.bgClass
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <h4 className="text-sm font-semibold text-foreground">
            {finding.title}
          </h4>
        </div>
        <Badge variant={config.badgeVariant}>{config.label}</Badge>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">
        {finding.description}
      </p>
      {finding.metric ? (
        <p className="mt-2 font-mono text-xs text-slate-400">{finding.metric}</p>
      ) : null}
    </div>
  );
}

export function RedTeamAlert({
  findings,
  title = "🩸 Red Team 漏洞審查",
  isLoading = false,
  error = null,
}: RedTeamAlertProps) {
  if (error) {
    return (
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-base text-destructive">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{error}</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!findings.length) {
    return null;
  }

  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h3>
        <p className="text-xs text-muted-foreground">
          做空機構紅隊視角 · 禁止為高分找藉口
        </p>
      </div>
      <div className="space-y-3">
        {findings.map((finding) => (
          <FindingItem key={finding.id} finding={finding} />
        ))}
      </div>
    </section>
  );
}
