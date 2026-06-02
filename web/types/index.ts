export type StrategyMode = "value" | "growth";

export interface QualityScore {
  value: number;
  max: number;
  label: string;
  grade: string;
  gradeEmoji: string;
}

export interface ValuationScore {
  value: number;
  max: number;
  label: string;
}

export interface ScoreDimension {
  id: string;
  label: string;
  earned: number;
  maxPoints: number;
  weightPct: number;
  rationale?: string;
}

export interface ScorecardResult {
  symbol: string;
  companyName: string;
  strategyMode: StrategyMode;
  quality: QualityScore;
  valuation: ValuationScore;
  dimensions: ScoreDimension[];
  metrics: MetricItem[];
}

export interface MetricItem {
  id: string;
  label: string;
  value: string;
  subtext?: string;
  tooltip?: string;
}

export type RedTeamSeverity = "critical" | "warning" | "info";

export interface RedTeamFinding {
  id: string;
  severity: RedTeamSeverity;
  title: string;
  description: string;
  metric?: string;
}

export interface StrategyWeights {
  mode: StrategyMode;
  label: string;
  tagline: string;
  weights: { dimension: string; pct: number; description: string }[];
}

export interface WatchlistEntry {
  symbol: string;
  companyName: string;
  qualityScore: number;
  valuationScore: number;
  grade: string;
}

export interface DashboardMockData {
  strategyWeights: Record<StrategyMode, StrategyWeights>;
  scorecard: ScorecardResult;
  redTeamFindings: RedTeamFinding[];
  watchlist: WatchlistEntry[];
}

export type AsyncState = "idle" | "loading" | "success" | "error";

export interface ApiErrorBody {
  detail?: string | { detail?: string; code?: string };
  code?: string;
}

export interface FcfHistoryPoint {
  fiscalYear: number;
  freeCashFlow: number;
  periodEnd?: string;
  source?: string;
}

export type HunterUniverse = "dow30" | "sp500" | "nasdaq100" | "custom";

export interface HunterScanRequest {
  universe: HunterUniverse;
  tickers?: string[];
  mode: StrategyMode;
  minDropPercent: number;
  enrichScores?: boolean;
  enrichTags?: boolean;
}

export interface TurnaroundCandidate {
  symbol: string;
  companyName: string;
  drawdownPct: number;
  currentPrice: number;
  sixMonthHigh: number;
  latestFcf: number;
  latestFcfFiscalYear?: number | null;
  fcfSource?: string;
  interestCoverage?: number | null;
  grossMargin?: number | null;
  grossMarginYoyChangePp?: number | null;
  netDebtEbitda?: number | null;
  fiftyTwoWeekHigh?: number | null;
  priceVs52wHigh?: number | null;
  pegRatio?: number | null;
  valueDefenseScore?: number | null;
  valueGradeEmoji?: string;
  valueGradeLabel?: string;
  reasonTag?: string;
  reasonComment?: string;
  redTeamFlag: boolean;
}

export interface HunterScanResponse {
  candidates: TurnaroundCandidate[];
  scannedCount: number;
  hitCount: number;
  universe: string;
  universeSource: string;
  minDropPercent: number;
}

export interface HunterScanTaskCreated {
  taskId: string;
}

export interface HunterTaskStatus {
  taskId: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  message: string;
  result?: HunterScanResponse | null;
  error?: string | null;
  errorCode?: string | null;
  updatedAt?: string | null;
}

export interface NarrativeResult {
  data: NarrativeResponse;
  usedMock: boolean;
  apiError: string | null;
  fetchedAt: string;
}

export interface AnalyzeResponse {
  scorecard: ScorecardResult;
  redTeamFindings: RedTeamFinding[];
  analystCommentary?: string | null;
  fcfHistory?: FcfHistoryPoint[];
  dataSource?: "live" | "cache" | "mock";
}

export interface NarrativeResponse {
  symbol: string;
  text: string;
  liveNewsDegraded: boolean;
  strategyMode: StrategyMode;
}

export interface ComponentStateProps {
  isLoading?: boolean;
  error?: string | null;
}
