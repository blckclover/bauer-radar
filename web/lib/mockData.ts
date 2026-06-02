import type {
  DashboardMockData,
  RedTeamFinding,
  ScorecardResult,
  StrategyMode,
  StrategyWeights,
  WatchlistEntry,
} from "@/types";

export const VALUE_WEIGHTS: StrategyWeights = {
  mode: "value",
  label: "價值防禦模式",
  tagline: "Red Team · 剝離好公司 vs 好價格",
  weights: [
    {
      dimension: "企業品質與護城河",
      pct: 30,
      description: "ROIC/ROA、毛利率波動、營業利益率",
    },
    {
      dimension: "財務安全防線",
      pct: 25,
      description: "Net Debt/EBITDA、利息保障倍數",
    },
    {
      dimension: "現金流品質",
      pct: 25,
      description: "FCF 支付率、股息連續成長",
    },
    {
      dimension: "營收穩定",
      pct: 20,
      description: "5Y 營收 CAGR、TTM 營收增速",
    },
  ],
};

export const GROWTH_WEIGHTS: StrategyWeights = {
  mode: "growth",
  label: "動能成長模式",
  tagline: "Red Team · 剝離成長敘事 vs 估值透支",
  weights: [
    {
      dimension: "基本面增長",
      pct: 30,
      description: "營收/獲利動能、CapEx 轉換",
    },
    {
      dimension: "預期修正",
      pct: 25,
      description: "Surprise streak、分析師修正",
    },
    {
      dimension: "PEG 估值剪刀差",
      pct: 25,
      description: "Forward PEG、成長/估值平衡",
    },
    {
      dimension: "Timing 輔助",
      pct: 15,
      description: "右側均線結構、中期支撐",
    },
    {
      dimension: "風險緩衝",
      pct: 5,
      description: "Beta、波動與回撤緩衝",
    },
  ],
};

const MOCK_VALUE_SCORECARD: ScorecardResult = {
  symbol: "AAPL",
  companyName: "Apple Inc.",
  strategyMode: "value",
  quality: {
    value: 88.5,
    max: 100,
    label: "企業品質分",
    grade: "財務防禦確立",
    gradeEmoji: "🛡️",
  },
  valuation: {
    value: 62.0,
    max: 100,
    label: "估值安全邊際",
  },
  dimensions: [
    {
      id: "quality",
      label: "企業品質 · 30%",
      earned: 26.5,
      maxPoints: 30,
      weightPct: 30,
      rationale: "ROIC 穩健、毛利率波動可控",
    },
    {
      id: "safety",
      label: "財務安全 · 25%",
      earned: 22.0,
      maxPoints: 25,
      weightPct: 25,
      rationale: "淨負債/EBITDA 低於 1.5x",
    },
    {
      id: "cashflow",
      label: "現金流品質 · 25%",
      earned: 21.0,
      maxPoints: 25,
      weightPct: 25,
      rationale: "FCF 支付率 18%，股息安全",
    },
    {
      id: "revenue",
      label: "營收穩定 · 20%",
      earned: 19.0,
      maxPoints: 20,
      weightPct: 20,
      rationale: "5Y 營收 CAGR 8.2%",
    },
  ],
  metrics: [
    {
      id: "roic",
      label: "ROIC",
      value: "42.1%",
      tooltip: "投入資本回報率",
    },
    {
      id: "peg",
      label: "前瞻 PEG",
      value: "1.82",
      tooltip: "成長/估值剪刀差",
    },
    {
      id: "fcf-yield",
      label: "FCF Yield",
      value: "3.4%",
      tooltip: "FCF / 市值",
    },
    {
      id: "nd-ebitda",
      label: "淨債務/EBITDA",
      value: "0.8x",
      tooltip: "槓桿安全線",
    },
  ],
};

const MOCK_GROWTH_SCORECARD: ScorecardResult = {
  symbol: "NVDA",
  companyName: "NVIDIA Corporation",
  strategyMode: "growth",
  quality: {
    value: 91.2,
    max: 100,
    label: "企業品質分",
    grade: "右側結構確立",
    gradeEmoji: "🚀",
  },
  valuation: {
    value: 48.5,
    max: 100,
    label: "估值安全邊際",
  },
  dimensions: [
    {
      id: "fundamental",
      label: "基本面增長 · 30%",
      earned: 27.5,
      maxPoints: 30,
      weightPct: 30,
    },
    {
      id: "surprise",
      label: "預期修正 · 25%",
      earned: 22.0,
      maxPoints: 25,
      weightPct: 25,
    },
    {
      id: "peg",
      label: "PEG 估值 · 25%",
      earned: 14.0,
      maxPoints: 25,
      weightPct: 25,
    },
    {
      id: "timing",
      label: "Timing · 15%",
      earned: 13.0,
      maxPoints: 15,
      weightPct: 15,
    },
    {
      id: "risk",
      label: "風險緩衝 · 5%",
      earned: 4.7,
      maxPoints: 5,
      weightPct: 5,
    },
  ],
  metrics: [
    {
      id: "peg",
      label: "前瞻 PEG",
      value: "1.12",
      subtext: "成長/估值剪刀差",
    },
    {
      id: "capex",
      label: "CapEx 擴張率",
      value: "+34.2%",
      subtext: "季 YoY",
    },
    {
      id: "surprise",
      label: "近一季 Surprise",
      value: "+8.4%",
      subtext: "連續超預期 4 季",
    },
    {
      id: "gross",
      label: "毛利率",
      value: "74.8%",
      subtext: "定價權 proxy",
    },
  ],
};

const MOCK_RED_TEAM: RedTeamFinding[] = [
  {
    id: "rt-1",
    severity: "warning",
    title: "估值透支風險",
    description:
      "企業品質分 ≥70 但估值安全分 <50，需警惕「偉大公司買太貴」陷阱。",
    metric: "Quality 91.2 / Valuation 48.5",
  },
  {
    id: "rt-2",
    severity: "critical",
    title: "CapEx 轉換率待驗證",
    description:
      "CapEx 激增若無法轉化為毛利擴張，估值下修風險顯著。",
    metric: "CapEx +34.2% YoY",
  },
  {
    id: "rt-3",
    severity: "info",
    title: "右側結構確立",
    description: "價格站上 SMA20 & SMA50，中期均線支撐有效。",
  },
];

const MOCK_WATCHLIST: WatchlistEntry[] = [
  {
    symbol: "AAPL",
    companyName: "Apple Inc.",
    qualityScore: 88.5,
    valuationScore: 62.0,
    grade: "🛡️ 財務防禦確立",
  },
  {
    symbol: "MSFT",
    companyName: "Microsoft Corp.",
    qualityScore: 90.1,
    valuationScore: 58.3,
    grade: "🛡️ 財務防禦確立",
  },
  {
    symbol: "NVDA",
    companyName: "NVIDIA Corp.",
    qualityScore: 91.2,
    valuationScore: 48.5,
    grade: "🚀 右側結構確立",
  },
];

export function getMockDashboardData(mode: StrategyMode): DashboardMockData {
  return {
    strategyWeights: {
      value: VALUE_WEIGHTS,
      growth: GROWTH_WEIGHTS,
    },
    scorecard: mode === "growth" ? MOCK_GROWTH_SCORECARD : MOCK_VALUE_SCORECARD,
    redTeamFindings: MOCK_RED_TEAM,
    watchlist: MOCK_WATCHLIST,
  };
}

export function getStrategyWeights(mode: StrategyMode): StrategyWeights {
  return mode === "growth" ? GROWTH_WEIGHTS : VALUE_WEIGHTS;
}
