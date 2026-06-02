import { AlertTriangle, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatScore, scoreTone } from "@/lib/utils";
import type { AnalyzeResponse } from "@/types";

interface StockHeroScoresProps {
  data: AnalyzeResponse;
  deathPenalty: boolean;
}

const toneClasses = {
  high: "text-emerald-400",
  mid: "text-slate-300",
  low: "text-red-400",
};

function HeroScoreCard({
  title,
  subtitle,
  score,
  grade,
  gradeEmoji,
  variant,
  deathPenalty,
}: {
  title: string;
  subtitle: string;
  score: number;
  grade?: string;
  gradeEmoji?: string;
  variant: "quality" | "valuation";
  deathPenalty: boolean;
}) {
  const tone = scoreTone(score);
  const showDeathRing = deathPenalty && variant === "quality";

  return (
    <Card
      className={cn(
        "relative overflow-hidden border-border/60 bg-card/80 backdrop-blur",
        showDeathRing &&
          "border-red-500/60 ring-2 ring-red-500/30 shadow-[0_0_40px_-12px_rgba(239,68,68,0.45)]"
      )}
    >
      {showDeathRing ? (
        <div className="flex items-center gap-2 border-b border-red-500/30 bg-red-500/10 px-4 py-2 text-xs font-semibold text-red-300">
          <ShieldAlert className="h-3.5 w-3.5" />
          死亡懲罰已觸發 · Red Team 封頂 69
        </div>
      ) : null}
      <CardHeader className="pb-2 pt-5">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            {title}
          </CardTitle>
          <Badge variant={variant === "quality" ? "success" : "secondary"}>
            {variant === "quality" ? "Quality" : "Valuation"}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </CardHeader>
      <CardContent className="space-y-3 pb-8">
        <div
          className={cn(
            "text-6xl font-extrabold tabular-nums tracking-tight sm:text-7xl",
            toneClasses[tone],
            showDeathRing && "text-red-400"
          )}
        >
          {formatScore(score)}
        </div>
        <p className="text-xs text-muted-foreground">
          滿分 100 · Red Team 封頂 95
          {showDeathRing ? " · 品質分已強制封頂" : ""}
        </p>
        {grade ? (
          <p className="text-base font-medium text-foreground">
            {gradeEmoji ? `${gradeEmoji} ` : ""}
            {grade}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function StockHeroScores({ data, deathPenalty }: StockHeroScoresProps) {
  const { quality, valuation } = data.scorecard;
  const valuationTrap =
    quality.value >= 70 && valuation.value < 50 && !deathPenalty;

  return (
    <section className="space-y-4">
      {valuationTrap ? (
        <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100/90">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>品質極優，但估值過高（估值安全分 &lt; 50），注意安全邊際。</p>
        </div>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <HeroScoreCard
          title={quality.label}
          subtitle="Business Quality Score · 企業品質分"
          score={quality.value}
          grade={quality.grade}
          gradeEmoji={quality.gradeEmoji}
          variant="quality"
          deathPenalty={deathPenalty}
        />
        <HeroScoreCard
          title={valuation.label}
          subtitle="Valuation Safety Score · 估值安全邊際"
          score={valuation.value}
          variant="valuation"
          deathPenalty={false}
        />
      </div>
    </section>
  );
}
