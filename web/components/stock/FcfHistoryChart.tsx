"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMoneyLarge } from "@/lib/format";
import type { FcfHistoryPoint } from "@/types";

interface FcfHistoryChartProps {
  points: FcfHistoryPoint[];
}

export function FcfHistoryChart({ points }: FcfHistoryChartProps) {
  if (!points.length) {
    return (
      <Card className="border-border/60 bg-card/50">
        <CardHeader>
          <CardTitle className="text-base">FCF 歷史</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">無 FCF 歷史資料。</p>
        </CardContent>
      </Card>
    );
  }

  const data = [...points]
    .sort((a, b) => a.fiscalYear - b.fiscalYear)
    .map((p) => ({
      year: String(p.fiscalYear),
      fcfB: p.freeCashFlow / 1e9,
      label: formatMoneyLarge(p.freeCashFlow),
    }));

  return (
    <Card className="border-border/60 bg-card/50">
      <CardHeader>
        <CardTitle className="text-base">FCF 歷史 · Free Cash Flow</CardTitle>
        <p className="text-xs text-muted-foreground">USD billions · 資料來源後端 API</p>
      </CardHeader>
      <CardContent className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="year"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
            />
            <YAxis
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
              tickFormatter={(v: number) => `$${v.toFixed(1)}B`}
            />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
              }}
              formatter={(value: number, _name: string, item) => {
                const payload = item.payload as { label: string };
                return [payload.label, "FCF"];
              }}
              labelFormatter={(label) => `FY ${label}`}
            />
            <Bar dataKey="fcfB" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={48} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
