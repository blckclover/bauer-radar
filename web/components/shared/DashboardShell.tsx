"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import Link from "next/link";
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
import {
  buildWatchlistFromQueries,
  extractHeroData,
  parseTickerList,
  useAnalyzeQuery,
  useWatchlistQueries,
} from "@/hooks/useDashboardQueries";
import { getStrategyWeights } from "@/lib/mockData";
import type { StrategyMode, WatchlistEntry } from "@/types";

function WatchlistTable({
  items,
  isLoading,
  strategyMode,
}: {
  items: WatchlistEntry[];
  isLoading: boolean;
  strategyMode: StrategyMode;
}) {
  if (isLoading && !items.length) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        載入觀察清單中…
      </div>
    );
  }

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
              <td className="px-4 py-3 font-mono font-semibold">
                <Link
                  href={`/stock/${row.symbol}?mode=${strategyMode}`}
                  className="text-primary hover:underline"
                >
                  {row.symbol}
                </Link>
              </td>
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
  const [activeTickers, setActiveTickers] = useState<string[]>(() =>
    parseTickerList("AAPL, MSFT, NVDA")
  );

  const heroTicker = activeTickers[0] ?? "AAPL";
  const weights = useMemo(
    () => getStrategyWeights(strategyMode),
    [strategyMode]
  );

  const heroQuery = useAnalyzeQuery(heroTicker, strategyMode);
  const watchlistQueries = useWatchlistQueries(activeTickers, strategyMode);

  const {
    scorecard,
    redTeamFindings,
    isMock,
    isRateLimited,
    isLoading: heroLoading,
    isFetching,
    error: heroError,
  } = extractHeroData(heroQuery);

  const watchlist = buildWatchlistFromQueries(watchlistQueries);
  const watchlistLoading = watchlistQueries.some((q) => q.isLoading);

  function handleLoadWatchlist() {
    const parsed = parseTickerList(watchlistInput);
    if (parsed.length) {
      setActiveTickers(parsed);
    }
  }

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
                Dividend Analyzer · Phase 2
              </p>
              <h1 className="text-2xl font-bold tracking-tight text-foreground">
                股息安全 · 綜合分析儀表板
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                FastAPI + Next.js ·{" "}
                {isMock ? "Mock Fallback" : "Live API"}
                {isFetching && !heroLoading ? " · 更新中…" : ""}
              </p>
            </div>
            <StrategyModeToggle mode={strategyMode} onChange={setStrategyMode} />
          </div>
        </header>

        <div className="flex-1 space-y-8 p-6">
          {(isMock || isRateLimited || heroError) && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-200/90">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                {isRateLimited ? (
                  <p>AI 伺服器目前擁擠（429），已顯示 fallback 資料。</p>
                ) : isMock ? (
                  <p>
                    無法連線 FastAPI（{String(heroError?.message ?? "offline")}），
                    目前顯示 Mock Data。
                  </p>
                ) : (
                  <p>{String(heroError?.message ?? "資料載入發生錯誤")}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  請確認 API 已啟動：{" "}
                  <code className="rounded bg-muted px-1 py-0.5">
                    cd api && uvicorn app.main:app --reload
                  </code>
                </p>
              </div>
            </div>
          )}

          <Card className="border-border/60 bg-card/50">
            <CardHeader>
              <CardTitle className="text-base">自訂觀察清單</CardTitle>
              <CardDescription>
                輸入股票代號（逗號分隔）· 呼叫 GET /api/v1/analyze/{"{ticker}"}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row">
              <Input
                value={watchlistInput}
                onChange={(e) => setWatchlistInput(e.target.value)}
                placeholder="AAPL, MSFT, KO"
                aria-label="觀察清單股票代號"
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleLoadWatchlist();
                }}
              />
              <Button
                type="button"
                className="shrink-0"
                onClick={handleLoadWatchlist}
                disabled={heroLoading || watchlistLoading}
              >
                {heroLoading || watchlistLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    分析中…
                  </>
                ) : (
                  "載入分析"
                )}
              </Button>
            </CardContent>
          </Card>

          <section className="space-y-4">
            {scorecard ? (
              <div className="flex flex-wrap items-center gap-3">
                <Link href={`/stock/${scorecard.symbol}?mode=${strategyMode}`}>
                  <Badge
                    variant="outline"
                    className="cursor-pointer font-mono hover:border-primary"
                  >
                    {scorecard.symbol}
                  </Badge>
                </Link>
                <h2 className="text-lg font-semibold text-foreground">
                  {scorecard.companyName}
                </h2>
                <Badge variant="secondary">{weights.label}</Badge>
                {isMock ? (
                  <Badge variant="warning">Mock</Badge>
                ) : (
                  <Badge variant="success">Live</Badge>
                )}
              </div>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <ScoreCard
                title="企業品質分"
                subtitle="Business Quality Score"
                score={scorecard?.quality.value ?? null}
                grade={scorecard?.quality.grade}
                gradeEmoji={scorecard?.quality.gradeEmoji}
                variant="quality"
                isLoading={heroLoading}
                error={
                  !heroLoading && !scorecard
                    ? "無法載入品質分"
                    : null
                }
              />
              <ScoreCard
                title="估值安全邊際"
                subtitle="Valuation Safety Score"
                score={scorecard?.valuation.value ?? null}
                variant="valuation"
                isLoading={heroLoading}
                error={
                  !heroLoading && !scorecard
                    ? "無法載入估值分"
                    : null
                }
              />
            </div>
          </section>

          <section className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              分項維度 · {weights.label}
            </h3>
            {heroLoading ? (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <ScoreCard key={i} title="載入中" score={null} isLoading />
                ))}
              </div>
            ) : scorecard?.dimensions?.length ? (
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
            ) : (
              <p className="text-sm text-muted-foreground">無分項得分資料。</p>
            )}
          </section>

          <section className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              前瞻硬指標 · Master Variables
            </h3>
            {heroLoading ? (
              <MetricCardGrid>
                {Array.from({ length: 4 }).map((_, i) => (
                  <MetricCard key={i} label="—" value="—" isLoading />
                ))}
              </MetricCardGrid>
            ) : scorecard?.metrics?.length ? (
              <MetricCardGrid>
                {scorecard.metrics.map((metric) => (
                  <MetricCard
                    key={metric.id}
                    label={metric.label}
                    value={metric.value || "N/A"}
                    subtext={metric.subtext}
                    tooltip={metric.tooltip}
                  />
                ))}
              </MetricCardGrid>
            ) : (
              <p className="text-sm text-muted-foreground">無 Master 指標資料。</p>
            )}
          </section>

          {redTeamFindings.length > 0 ? (
            <>
              <Separator />
              <RedTeamAlert
                findings={redTeamFindings}
                isLoading={heroLoading}
              />
            </>
          ) : null}

          <Separator />

          <section className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              綜合摘要 · Watchlist Summary
            </h3>
            <WatchlistTable
              items={watchlist}
              isLoading={watchlistLoading}
              strategyMode={strategyMode}
            />
          </section>
        </div>
      </main>
    </div>
  );
}
