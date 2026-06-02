"use client";

import { Shield, TrendingUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { StrategyMode } from "@/types";

interface StrategyModeToggleProps {
  mode: StrategyMode;
  onChange: (mode: StrategyMode) => void;
}

export function StrategyModeToggle({ mode, onChange }: StrategyModeToggleProps) {
  return (
    <div className="inline-flex rounded-lg border border-border/60 bg-card/60 p-1">
      <Button
        type="button"
        variant={mode === "value" ? "default" : "ghost"}
        size="sm"
        className={cn("gap-2", mode === "value" && "shadow-sm")}
        onClick={() => onChange("value")}
      >
        <Shield className="h-4 w-4" />
        價值防禦模式
      </Button>
      <Button
        type="button"
        variant={mode === "growth" ? "default" : "ghost"}
        size="sm"
        className={cn("gap-2", mode === "growth" && "shadow-sm")}
        onClick={() => onChange("growth")}
      >
        <TrendingUp className="h-4 w-4" />
        動能成長模式
      </Button>
    </div>
  );
}
