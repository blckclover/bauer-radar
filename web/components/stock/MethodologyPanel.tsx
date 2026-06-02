"use client";

import { ChevronDown } from "lucide-react";

import { Separator } from "@/components/ui/separator";
import type { StrategyWeights } from "@/types";

const DEATH_RULES = [
  {
    title: "淨債務/EBITDA > 3.0x",
    description: "觸發財務安全一票否決，企業品質分強制封頂 69。",
  },
  {
    title: "FCF 支付率 > 90%",
    description: "觸發現金流一票否決，該維度歸零並額外扣分。",
  },
  {
    title: "Red Team 封頂",
    description: "所有子分數上限 95，避免模型過度樂觀。",
  },
];

interface MethodologyPanelProps {
  weights: StrategyWeights;
}

export function MethodologyPanel({ weights }: MethodologyPanelProps) {
  return (
    <details className="group rounded-lg border border-border/60 bg-card/40">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 font-medium text-foreground marker:content-none">
        <div>
          <p className="text-sm font-semibold">📐 量化因子方法論 · Factor Methodology</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {weights.label} · {weights.tagline}
          </p>
        </div>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-5 border-t border-border/60 px-5 py-5">
        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            權重配置
          </p>
          <div className="space-y-3">
            {weights.weights.map((item) => (
              <div
                key={item.dimension}
                className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between"
              >
                <div>
                  <p className="text-sm font-medium text-foreground">{item.dimension}</p>
                  <p className="text-xs text-muted-foreground">{item.description}</p>
                </div>
                <span className="font-mono text-sm font-semibold text-emerald-400">
                  {item.pct}%
                </span>
              </div>
            ))}
          </div>
        </div>
        <Separator />
        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-red-400/90">
            死亡懲罰規則 · Death Penalty
          </p>
          <ul className="space-y-2">
            {DEATH_RULES.map((rule) => (
              <li
                key={rule.title}
                className="rounded-md border border-red-500/20 bg-red-500/5 px-3 py-2"
              >
                <p className="text-sm font-medium text-red-300">{rule.title}</p>
                <p className="text-xs text-muted-foreground">{rule.description}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </details>
  );
}
