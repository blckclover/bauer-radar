"use client";

import { useMemo, useState } from "react";

import { DashboardSidebar } from "@/components/shared/DashboardSidebar";
import { MetricCard, MetricCardGrid } from "@/components/shared/MetricCard";
import { RedTeamAlert } from "@/components/shared/RedTeamAlert";
import { ScoreCard } from "@/components/shared/ScoreCard";
import { StrategyModeToggle } from "@/components/shared/StrategyModeToggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { getMockDashboardData, getStrategyWeights } from "@/lib/mockData";
import type { StrategyMode, WatchlistEntry } from "@/types";

function WatchlistTable({ items }: { items: WatchlistEntry[] }) {
  if (!items.length) {
    return (
      <p className="text-sm text-muted-foreground">尚未加入任何觀察標的。</p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border/60">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead className="border-b border-border/60 bg-muted/30 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-4 py-3 font-medium">代號</th>
            <th className="px-4 py-3 font-medium">公司</th>
            <th className="px-4 py-3 font-medium">品質分</th>
            <th className="px-4 py-3 font-medium">估值分</th>
            <th className="px-4 py-3 font-medium">等級</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr
              key={row.symbol}
              className="border-b border-border/40 last:border-0 hover:bg-muted/20"
            >
              <td className="px-4 py-3 font-mono font-semibold">{row.symbol}</td>
              <td className="px-4 py-3 text-muted-foreground">{row.companyName}</td>
              <td className="px-4 py-3 tabular-nums">{row.qualityScore.toFixed(1)}</td>
              <td className="px-4 py-3 tabular-nums">{row.valuationScore.toFixed(1)}</td>
              <td className="px-4 py-3">{row.grade}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DashboardShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [strategyMode, setStrategyMode] = useState<StrategyMode>("value");
  const [watchlistInput, setWatchlistInput] = useState("AAPL, MSFT, NVDA");

  const data = useMemo(
    () => getMockDashboardData(strategyMode),
    [strategyMode]
  );
  const weights = useMemo(
    () => getStrategyWeights(strategyMode),
    [strategyMode]
  );

  const { scorecard, redTeamFindings, watchlist } = data;

  return (
    <div className="flex min-h-screen bg-background">
      <DashboardSidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((prev) => !prev)}
        weights={weights}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-border/60 bg-card/30 px-6 py-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400/90">
                Dividend Analyzer · Phase 1
              </p>
              <h1 className="text-2xl font-bold tracking-tight text-foreground">
                股息安全 · 綜合分析儀表板
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Next.js + Tailwind + shadcn/ui · Mock Data 骨架
              </p>
            </div>
            <StrategyModeToggle mode={strategyMode} onChange={setStrategyMode} />
          </div>
        </header>

        <div className="flex-1 space-y-8 p-6">
          {/* Watchlist input */}
          <Card className="border-border/60 bg-card/50">
            <CardHeader>
              <CardTitle className="text-base">自訂觀察清單</CardTitle>
              <CardDescription>
                輸入股票代號（逗號分隔）· 第二階段將對接後端 API
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row">
              <Input
                value={watchlistInput}
                onChange={(e) => setWatchlistInput(e.target.value)}
                placeholder="AAPL, MSFT, KO"
                aria-label="觀察清單股票代號"
              />
              <Button type="button" className="shrink-0">
                載入分析
              </Button>
            </CardContent>
          </Card>

          {/* Hero scores */}
          <section className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="outline" className="font-mono">
                {scorecard.symbol}
              </Badge>
              <h2 className="text-lg font-semibold text-foreground">
                {scorecard.companyName}
              </h2>
              <Badge variant="secondary">{weights.label}</Badge>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <ScoreCard
                title={scorecard.quality.label}
                subtitle="Business Quality Score"
                score={scorecard.quality.value}
                grade={scorecard.quality.grade}
                gradeEmoji={scorecard.quality.gradeEmoji}
                variant="quality"
              />
              <ScoreCard
                title={scorecard.valuation.label}
                subtitle="Valuation Safety Score"
                score={scorecard.valuation.value}
                variant="valuation"
              />
            </div>
          </section>

          {/* Dimension breakdown */}
          <section className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              分項維度 · {weights.label}
            </h3>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {scorecard.dimensions.map((dim) => (
                <Card key={dim.id} className="border-border/60 bg-card/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{dim.label}</CardTitle>
                    {dim.rationale ? (
                      <CardDescription className="text-xs">
                        {dim.rationale}
                      </CardDescription>
                    ) : null}
                  </CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold tabular-nums text-foreground">
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

          {/* Master metrics */}
          <section className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              前瞻硬指標 · Master Variables
            </h3>
            <MetricCardGrid>
              {scorecard.metrics.map((metric) => (
                <MetricCard
                  key={metric.id}
                  label={metric.label}
                  value={metric.value}
                  subtext={metric.subtext}
                  tooltip={metric.tooltip}
                />
              ))}
            </MetricCardGrid>
          </section>

          <Separator />

          <RedTeamAlert findings={redTeamFindings} />

          <Separator />

          {/* Watchlist summary */}
          <section className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              綜合摘要 · Watchlist Summary
            </h3>
            <WatchlistTable items={watchlist} />
          </section>
        </div>
      </main>
    </div>
  );
}
