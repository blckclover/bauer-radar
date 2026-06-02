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

export interface AnalyzeResponse {
  scorecard: ScorecardResult;
  redTeamFindings: RedTeamFinding[];
  analystCommentary?: string | null;
  dataSource?: "live" | "cache" | "mock";
}

export interface NarrativeResponse {
  symbol: string;
  text: string;
  liveNewsDegraded: boolean;
  strategyMode: StrategyMode;
}

export interface ApiErrorBody {
  detail?: string | { detail?: string; code?: string };
  code?: string;
}
