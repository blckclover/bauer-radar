import Link from "next/link";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import { Suspense } from "react";

import { MetricCard, MetricCardGrid } from "@/components/shared/MetricCard";
import { RedTeamAlert } from "@/components/shared/RedTeamAlert";
import { MethodologyPanel } from "@/components/stock/MethodologyPanel";
import { StockHeroScores } from "@/components/stock/StockHeroScores";
import { StockModeToggle } from "@/components/stock/StockModeToggle";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { hasDeathPenalty, sanitizeRedTeamFindings, type StockAnalysisResult } from "@/lib/api";
import { getStrategyWeights } from "@/lib/mockData";
import type { StrategyMode } from "@/types";

interface StockDetailViewProps {
  ticker: string;
  mode: StrategyMode;
  result: StockAnalysisResult;
}

function DataSourceBanner({ result }: { result: StockAnalysisResult }) {
  if (!result.usedMock && !result.apiError && !result.validationError) {
    return null;
  }

  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-100/90">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="space-y-1">
        {result.usedMock ? (
          <p>
            無法取得即時 API 資料
            {result.apiError ? `（${result.apiError}）` : ""}
            ，目前顯示 Mock Fallback。
          </p>
        ) : null}
        {result.validationError ? (
          <p className="text-xs text-muted-foreground">
            資料驗證警告：{result.validationError}
          </p>
        ) : null}
        <p className="text-xs text-muted-foreground">
          請確認 FastAPI 已啟動：
          <code className="ml-1 rounded bg-muted px-1 py-0.5">
            cd api && uvicorn app.main:app --reload
          </code>
        </p>
      </div>
    </div>
  );
}

export function StockDetailView({ ticker, mode, result }: StockDetailViewProps) {
  const { scorecard } = result.data;
  const redTeamFindings = sanitizeRedTeamFindings(result.data.redTeamFindings);
  const deathPenalty = hasDeathPenalty(result.data);
  const weights = getStrategyWeights(mode);
  const metrics = scorecard.metrics ?? [];

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/60 bg-card/30">
        <div className="mx-auto max-w-6xl px-4 py-5 sm:px-6 lg:px-8">
          <div className="mb-4">
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" />
              返回 Dashboard
            </Link>
          </div>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="font-mono text-base">
                  {scorecard.symbol || ticker.toUpperCase()}
                </Badge>
                {result.usedMock ? (
                  <Badge variant="warning">Mock</Badge>
                ) : (
                  <Badge variant="success">Live API</Badge>
                )}
                <Badge variant="secondary">{weights.label}</Badge>
              </div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
                {scorecard.companyName || ticker.toUpperCase()}
              </h1>
              <p className="text-sm text-muted-foreground">
                個股深度分析 · Phase 3 · GET /api/v1/analyze/{ticker.toUpperCase()}
              </p>
            </div>
            <Suspense fallback={<div className="h-10 w-64 animate-pulse rounded-lg bg-muted" />}>
              <StockModeToggle mode={mode} />
            </Suspense>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        <DataSourceBanner result={result} />

        <StockHeroScores data={result.data} deathPenalty={deathPenalty} />

        <section className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            前瞻硬指標 · Master Variables
          </h2>
          {metrics.length > 0 ? (
            <MetricCardGrid columns={4}>
              {metrics.map((metric) => (
                <MetricCard
                  key={metric.id}
                  label={metric.label}
                  value={metric.value || "N/A"}
                  subtext={metric.subtext ?? undefined}
                  tooltip={metric.tooltip ?? undefined}
                />
              ))}
            </MetricCardGrid>
          ) : (
            <p className="text-sm text-muted-foreground">無可用指標資料。</p>
          )}
        </section>

        {scorecard.dimensions.length > 0 ? (
          <section className="space-y-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              分項維度得分
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {scorecard.dimensions.map((dim) => (
                <Card key={dim.id} className="border-border/60 bg-card/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm leading-snug">{dim.label}</CardTitle>
                    {dim.rationale ? (
                      <CardDescription className="text-xs line-clamp-3">
                        {dim.rationale}
                      </CardDescription>
                    ) : null}
                  </CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold tabular-nums">
                      {dim.earned.toFixed(1)}
                      <span className="text-base font-normal text-muted-foreground">
                        {" "}
                        / {dim.maxPoints}
                      </span>
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        ) : null}

        {redTeamFindings.length > 0 ? (
          <>
            <Separator />
            <RedTeamAlert findings={redTeamFindings} />
          </>
        ) : null}

        <Separator />

        <MethodologyPanel weights={weights} />
      </main>
    </div>
  );
}
