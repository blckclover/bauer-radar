"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { StrategyModeToggle } from "@/components/shared/StrategyModeToggle";
import type { StrategyMode } from "@/types";

interface StockModeToggleProps {
  mode: StrategyMode;
}

export function StockModeToggle({ mode }: StockModeToggleProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const handleChange = useCallback(
    (next: StrategyMode) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("mode", next);
      router.push(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams]
  );

  return <StrategyModeToggle mode={mode} onChange={handleChange} />;
}
