"use client";

import { AlertCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatScore, scoreTone } from "@/lib/utils";
import type { ComponentStateProps } from "@/types";

export interface ScoreCardProps extends ComponentStateProps {
  title: string;
  subtitle?: string;
  score: number | null;
  maxScore?: number;
  grade?: string;
  gradeEmoji?: string;
  variant?: "quality" | "valuation";
}

const toneClasses = {
  high: "text-emerald-400",
  mid: "text-slate-300",
  low: "text-red-400",
};

export function ScoreCard({
  title,
  subtitle,
  score,
  maxScore = 100,
  grade,
  gradeEmoji,
  variant = "quality",
  isLoading = false,
  error = null,
}: ScoreCardProps) {
  const tone = scoreTone(score);

  if (error) {
    return (
      <Card className="border-destructive/40 bg-card/80">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base text-destructive">
            <AlertCircle className="h-4 w-4" />
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{error}</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card className="border-border/60 bg-card/80">
        <CardHeader className="pb-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="mt-2 h-3 w-48" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-12 w-24" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/60 bg-card/80 backdrop-blur">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {title}
          </CardTitle>
          <Badge variant={variant === "quality" ? "success" : "secondary"}>
            {variant === "quality" ? "Quality" : "Valuation"}
          </Badge>
        </div>
        {subtitle ? (
          <CardDescription className="text-xs">{subtitle}</CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-2">
        <div
          className={cn(
            "text-5xl font-bold tabular-nums tracking-tight",
            toneClasses[tone]
          )}
        >
          {formatScore(score)}
        </div>
        <p className="text-xs text-muted-foreground">滿分 {maxScore} · Red Team 封頂 95</p>
        {grade ? (
          <p className="text-sm font-medium text-foreground">
            {gradeEmoji ? `${gradeEmoji} ` : ""}
            {grade}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function ScoreCardLoading({ title }: { title: string }) {
  return (
    <ScoreCard title={title} score={null} isLoading />
  );
}
