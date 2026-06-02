"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Radar,
  ShieldAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { StockModeToggle } from "@/components/stock/StockModeToggle";
import { DataFreshnessBar } from "@/components/shared/DataFreshnessBar";
import { MetricCard, MetricCardGrid } from "@/components/shared/MetricCard";
import { RedTeamAlert } from "@/components/shared/RedTeamAlert";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ApiClientError,
  cancelHunterTask,
  getHunterTaskStatus,
  parseTickerList,
  startHunterScan,
} from "@/lib/api";
import {
  formatCoverage,
  formatGrossMargin,
  formatMoneyLarge,
  formatPctOffHigh,
} from "@/lib/format";
import { parseStrategyMode } from "@/lib/schemas";
import type {
  HunterScanResponse,
  HunterUniverse,
  StrategyMode,
  TurnaroundCandidate,
} from "@/types";

type SortKey =
  | "symbol"
  | "drawdownPct"
  | "latestFcf"
  | "valueDefenseScore"
  | "pegRatio";

interface ReversalScanWorkspaceProps {
  initialMode: StrategyMode;
}

function SortButton({
  label,
  active,
  direction,
  onClick,
}: {
  label: string;
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 hover:text-foreground"
    >
      {label}
      {active ? (
        direction === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-40" />
      )}
    </button>
  );
}

function ResultsTable({
  rows,
  mode,
}: {
  rows: TurnaroundCandidate[];
  mode: StrategyMode;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border/60">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead>Ticker</TableHead>
            <TableHead>公司名稱</TableHead>
            <TableHead className="text-red-400">半年跌幅</TableHead>
            <TableHead>最新 FCF</TableHead>
            <TableHead>利息保障</TableHead>
            <TableHead>毛利率 YoY</TableHead>
            <TableHead>估值吸引力</TableHead>
            <TableHead>防禦得分</TableHead>
            <TableHead>Red Team</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.symbol}>
              <TableCell className="font-mono font-semibold">
                <Link
                  href={`/stock/${row.symbol}?mode=${mode}`}
                  className="text-primary hover:underline"
                >
                  {row.symbol}
                </Link>
              </TableCell>
              <TableCell className="max-w-[160px] truncate text-muted-foreground">
                {row.companyName}
              </TableCell>
              <TableCell className="font-bold text-red-400">
                -{row.drawdownPct.toFixed(1)}%
              </TableCell>
              <TableCell className="font-medium text-emerald-400">
                {formatMoneyLarge(row.latestFcf)}
              </TableCell>
              <TableCell>{formatCoverage(row.interestCoverage)}</TableCell>
              <TableCell className="text-xs">
                {formatGrossMargin(row.grossMargin, row.grossMarginYoyChangePp)}
              </TableCell>
              <TableCell className="text-xs">
                <div>PEG {row.pegRatio != null ? row.pegRatio.toFixed(2) : "—"}</div>
                <div className="text-muted-foreground">
                  距高點 {formatPctOffHigh(row.priceVs52wHigh)}
                </div>
              </TableCell>
              <TableCell>
                {row.valueDefenseScore != null
                  ? `${row.valueGradeEmoji} ${row.valueDefenseScore.toFixed(1)}`
                  : "—"}
              </TableCell>
              <TableCell>
                {row.redTeamFlag ? (
                  <Badge variant="destructive" className="gap-1">
                    <ShieldAlert className="h-3 w-3" />
                    警示
                  </Badge>
                ) : row.reasonTag ? (
                  <span className="text-xs text-muted-foreground">
                    {row.reasonTag}
                  </span>
                ) : (
                  "—"
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ReversalScanInner({ initialMode }: ReversalScanWorkspaceProps) {
  const searchParams = useSearchParams();
  const mode = parseStrategyMode(searchParams.get("mode") ?? initialMode);

  const [universe, setUniverse] = useState<HunterUniverse>("dow30");
  const [minDrop, setMinDrop] = useState(15);
  const [customTickers, setCustomTickers] = useState("");
  const [minScoreFilter, setMinScoreFilter] = useState(0);
  const [redTeamOnly, setRedTeamOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("valueDefenseScore");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [lastScan, setLastScan] = useState<HunterScanResponse | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const startMutation = useMutation({
    mutationFn: () => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      return startHunterScan(
        {
          universe,
          tickers: universe === "custom" ? parseTickerList(customTickers) : [],
          mode,
          minDropPercent: minDrop,
          enrichScores: true,
          enrichTags: false,
        },
        { signal: abortRef.current.signal }
      );
    },
    onSuccess: (data) => {
      setActiveTaskId(data.taskId);
      setLastScan(null);
      setLastUpdatedAt(null);
    },
  });

  const statusQuery = useQuery({
    queryKey: ["hunter-status", activeTaskId],
    queryFn: ({ signal }) => getHunterTaskStatus(activeTaskId!, { signal }),
    enabled: Boolean(activeTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || status === "completed" || status === "failed" || status === "cancelled") {
        return false;
      }
      return 2000;
    },
    retry: false,
  });

  useEffect(() => {
    const status = statusQuery.data;
    if (!status) return;
    if (status.status === "completed" && status.result) {
      setLastScan(status.result);
      setLastUpdatedAt(status.updatedAt ?? new Date().toISOString());
      setActiveTaskId(null);
    }
    if (status.status === "failed" || status.status === "cancelled") {
      setActiveTaskId(null);
    }
  }, [statusQuery.data]);

  const isScanning =
    startMutation.isPending ||
    Boolean(activeTaskId) ||
    statusQuery.data?.status === "pending" ||
    statusQuery.data?.status === "running";

  async function handleCancelScan() {
    abortRef.current?.abort();
    if (activeTaskId) {
      try {
        await cancelHunterTask(activeTaskId);
      } catch {
        // ignore cancel errors
      }
    }
    setActiveTaskId(null);
    startMutation.reset();
  }

  const filteredRows = useMemo(() => {
    if (!lastScan?.candidates.length) return [];
    let rows = [...lastScan.candidates];
    if (minScoreFilter > 0) {
      rows = rows.filter(
        (r) => (r.valueDefenseScore ?? 0) >= minScoreFilter
      );
    }
    if (redTeamOnly) {
      rows = rows.filter((r) => r.redTeamFlag);
    }
    rows.sort((a, b) => {
      const pick = (r: TurnaroundCandidate): number | string => {
        switch (sortKey) {
          case "symbol":
            return r.symbol;
          case "drawdownPct":
            return r.drawdownPct;
          case "latestFcf":
            return r.latestFcf;
          case "pegRatio":
            return r.pegRatio ?? 999;
          case "valueDefenseScore":
          default:
            return r.valueDefenseScore ?? -1;
        }
      };
      const av = pick(a);
      const bv = pick(b);
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === "asc"
        ? Number(av) - Number(bv)
        : Number(bv) - Number(av);
    });
    return rows;
  }, [lastScan, minScoreFilter, redTeamOnly, sortKey, sortDir]);

  const redTeamFindings = useMemo(() => {
    if (!lastScan?.candidates.length) return [];
    return lastScan.candidates
      .filter((r) => r.redTeamFlag && r.reasonComment)
      .map((r) => ({
        id: `hunter-${r.symbol}`,
        severity: "warning" as const,
        title: `${r.symbol} · ${r.reasonTag || "Red Team 警示"}`,
        description: r.reasonComment,
        metric: r.symbol,
      }));
  }, [lastScan]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const scanError =
    startMutation.error instanceof ApiClientError
      ? startMutation.error.message
      : startMutation.error instanceof Error
        ? startMutation.error.message
        : statusQuery.data?.status === "failed"
          ? statusQuery.data.error ?? "掃描失敗"
          : null;

  const scanProgress = statusQuery.data?.progress ?? (startMutation.isPending ? 5 : 0);
  const scanMessage =
    statusQuery.data?.message ??
    (startMutation.isPending ? "建立掃描任務中…" : "");

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/60 bg-card/30">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <div className="mb-3">
            <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
              ← 返回 Dashboard
            </Link>
          </div>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                Phase 5 · Reversal Scan
              </p>
              <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
                逆向轉機股雷達
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                POST /api/v1/hunter/scan · Background Task + 2s Polling
              </p>
              {lastScan ? (
                <DataFreshnessBar
                  dataSource="live"
                  updatedAt={lastUpdatedAt}
                  sourceLabel={lastScan.universeSource}
                  className="mt-2"
                />
              ) : null}
            </div>
            <StockModeToggle mode={mode} />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        <Card className="border-border/60 bg-card/50">
          <CardHeader>
            <CardTitle className="text-base">掃描條件設定</CardTitle>
            <CardDescription>
              跌幅門檻 · Universe · 毛利率穩定 · FCF &gt; 0 · 右側均線
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-2 text-sm">
              <span className="font-medium text-muted-foreground">Universe</span>
              <select
                value={universe}
                onChange={(e) => setUniverse(e.target.value as HunterUniverse)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="dow30">Dow 30（快速）</option>
                <option value="sp500">S&amp;P 500（完整）</option>
                <option value="nasdaq100">Nasdaq 100</option>
                <option value="custom">自訂清單</option>
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-muted-foreground">
                最低跌幅門檻 (%)
              </span>
              <Input
                type="number"
                min={5}
                max={60}
                value={minDrop}
                onChange={(e) => setMinDrop(Number(e.target.value) || 15)}
              />
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-muted-foreground">
                最低防禦得分
              </span>
              <Input
                type="number"
                min={0}
                max={100}
                value={minScoreFilter}
                onChange={(e) => setMinScoreFilter(Number(e.target.value) || 0)}
              />
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                checked={redTeamOnly}
                onChange={(e) => setRedTeamOnly(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              <span>僅顯示 Red Team 警示標的</span>
            </label>
            {universe === "custom" ? (
              <label className="space-y-2 text-sm md:col-span-2 lg:col-span-4">
                <span className="font-medium text-muted-foreground">
                  自訂 Ticker（逗號分隔）
                </span>
                <Input
                  value={customTickers}
                  onChange={(e) => setCustomTickers(e.target.value)}
                  placeholder="AAPL, MSFT, KO"
                />
              </label>
            ) : null}
          </CardContent>
        </Card>

        <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-center">
          <Button
            size="lg"
            className="gap-2 sm:min-w-[240px]"
            disabled={isScanning}
            onClick={() => startMutation.mutate()}
          >
            {isScanning ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                掃描進行中…
              </>
            ) : (
              <>
                <Radar className="h-5 w-5" />
                啟動大盤逆向掃描
              </>
            )}
          </Button>
          {isScanning ? (
            <Button
              type="button"
              variant="outline"
              size="lg"
              className="gap-2"
              onClick={() => void handleCancelScan()}
            >
              <X className="h-4 w-4" />
              取消掃描
            </Button>
          ) : null}
          {isScanning ? (
            <div className="flex-1 space-y-2">
              <p className="text-sm text-muted-foreground">
                {scanMessage || "正在掃描成分股，S&P 500 可能需要數分鐘…"}
              </p>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-emerald-500 transition-all duration-500"
                  style={{ width: `${Math.max(scanProgress, 5)}%` }}
                />
              </div>
            </div>
          ) : null}
          {lastScan ? (
            <p className="text-sm text-muted-foreground">
              已掃描 {lastScan.scannedCount} 檔 · 命中 {lastScan.hitCount} 檔 ·
              來源 {lastScan.universeSource}
            </p>
          ) : null}
        </div>

        {scanError ? (
          <div className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <div>
              <p className="font-medium text-destructive">掃描失敗</p>
              <p className="text-muted-foreground">{scanError}</p>
            </div>
          </div>
        ) : null}

        {lastScan ? (
          <MetricCardGrid columns={3}>
            <MetricCard
              label="已掃描"
              value={String(lastScan.scannedCount)}
              subtext={lastScan.universeSource}
            />
            <MetricCard
              label="命中標的"
              value={String(lastScan.hitCount)}
              subtext={`跌幅 ≥ ${lastScan.minDropPercent}%`}
            />
            <MetricCard
              label="Red Team 警示"
              value={String(
                lastScan.candidates.filter((r) => r.redTeamFlag).length
              )}
              subtext="需人工複核"
              tone={
                lastScan.candidates.some((r) => r.redTeamFlag)
                  ? "negative"
                  : "default"
              }
            />
          </MetricCardGrid>
        ) : null}

        {redTeamFindings.length > 0 ? (
          <RedTeamAlert findings={redTeamFindings} />
        ) : null}

        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              掃描結果
            </h2>
            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
              <SortButton
                label="代號"
                active={sortKey === "symbol"}
                direction={sortDir}
                onClick={() => toggleSort("symbol")}
              />
              <SortButton
                label="跌幅"
                active={sortKey === "drawdownPct"}
                direction={sortDir}
                onClick={() => toggleSort("drawdownPct")}
              />
              <SortButton
                label="FCF"
                active={sortKey === "latestFcf"}
                direction={sortDir}
                onClick={() => toggleSort("latestFcf")}
              />
              <SortButton
                label="防禦分"
                active={sortKey === "valueDefenseScore"}
                direction={sortDir}
                onClick={() => toggleSort("valueDefenseScore")}
              />
            </div>
          </div>

          {isScanning && !lastScan ? (
            <div className="space-y-3 rounded-lg border border-border/60 p-8 text-center">
              <Loader2 className="mx-auto h-8 w-8 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">載入掃描結果中…</p>
            </div>
          ) : null}

          {!isScanning && lastScan && filteredRows.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border/60 p-12 text-center">
              <p className="text-sm text-muted-foreground">
                無符合條件的轉機標的。可調低跌幅門檻或更換 Universe 後重試。
              </p>
            </div>
          ) : null}

          {filteredRows.length > 0 ? (
            <ResultsTable rows={filteredRows} mode={mode} />
          ) : null}
        </section>
      </main>
    </div>
  );
}

export function ReversalScanWorkspace(props: ReversalScanWorkspaceProps) {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <ReversalScanInner {...props} />
    </Suspense>
  );
}
