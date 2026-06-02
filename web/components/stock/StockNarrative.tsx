import { AlertTriangle } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { NarrativeResult } from "@/types";

interface StockNarrativeProps {
  narrative: NarrativeResult;
}

export function StockNarrative({ narrative }: StockNarrativeProps) {
  const { data, usedMock, apiError } = narrative;
  const text = data.text?.trim();

  if (!text) {
    return (
      <Card className="border-border/60 bg-card/50">
        <CardHeader>
          <CardTitle className="text-base">
            💡 科技願景與最新嘗試
          </CardTitle>
        </CardHeader>
        <CardContent>
          {usedMock || apiError ? (
            <div className="flex items-start gap-2 text-sm text-amber-200/90">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>
                {apiError
                  ? `敘事暫不可用（${apiError}）`
                  : "敘事資料暫不可用，請稍後重試。"}
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">尚無可用敘事內容。</p>
          )}
          {data.liveNewsDegraded ? (
            <p className="mt-2 text-xs text-muted-foreground">
              即時新聞流連線超時 · 目前顯示基礎科技敘事
            </p>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  const paragraphs = text.split(/\n+/).filter(Boolean);

  return (
    <Card className="border-border/60 bg-card/50">
      <CardHeader>
        <CardTitle className="text-base">
          💡 科技願景與最新嘗試 (Company Narrative)
        </CardTitle>
        {data.liveNewsDegraded ? (
          <p className="text-xs text-muted-foreground">
            即時新聞流連線超時 · 目前顯示基礎科技敘事
          </p>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-relaxed text-foreground/90">
        {paragraphs.map((para, idx) => (
          <p key={idx}>{para}</p>
        ))}
      </CardContent>
    </Card>
  );
}
