const HTML_FENCE_RE = /```(?:html)?\n?/gi;

/**
 * Strip Markdown code fences from AI-generated HTML/text.
 * Use before any future rich-text rendering (prefer plain text + components).
 */
export function stripMarkdownFences(content: string): string {
  if (!content) return "";
  return HTML_FENCE_RE.replace(content, "").replace(/```/g, "").trim();
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}
