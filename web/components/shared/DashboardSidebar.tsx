"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { StrategyWeights } from "@/types";

interface DashboardSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  weights: StrategyWeights;
}

export function DashboardSidebar({
  collapsed,
  onToggle,
  weights,
}: DashboardSidebarProps) {
  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-border/60 bg-card/40 transition-all duration-300",
        collapsed ? "w-14" : "w-72"
      )}
    >
      <div className="flex items-center justify-between border-b border-border/60 p-3">
        {!collapsed ? (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              量化評分標準
            </p>
            <p className="text-sm font-medium text-foreground">Factor Methodology</p>
          </div>
        ) : null}
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggle}
          aria-label={collapsed ? "展開側邊欄" : "收合側邊欄"}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </Button>
      </div>

      {!collapsed ? (
        <ScrollArea className="flex-1 p-4">
          <div className="mb-4 space-y-1">
            <p className="text-sm font-semibold text-foreground">{weights.label}</p>
            <p className="text-xs text-muted-foreground">{weights.tagline}</p>
          </div>
          <Separator className="my-4" />
          <div className="space-y-4">
            {weights.weights.map((item) => (
              <div key={item.dimension} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground">
                    {item.dimension}
                  </span>
                  <span className="font-mono text-xs text-emerald-400">
                    {item.pct}%
                  </span>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
          <Separator className="my-4" />
          <p className="text-xs leading-relaxed text-muted-foreground">
            100 分制財務紀律評分 · 雙軌制：企業品質分 + 估值安全邊際。
            Red Team 封頂 95 分，避免模型過度樂觀。
          </p>
        </ScrollArea>
      ) : (
        <div className="flex flex-1 items-start justify-center pt-4">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground [writing-mode:vertical-rl]">
            Methodology
          </span>
        </div>
      )}
    </aside>
  );
}
