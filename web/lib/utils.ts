import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatScore(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  return value.toFixed(digits);
}

export function scoreTone(value: number | null | undefined): "high" | "mid" | "low" {
  if (value === null || value === undefined) return "mid";
  if (value >= 85) return "high";
  if (value >= 70) return "mid";
  return "low";
}
