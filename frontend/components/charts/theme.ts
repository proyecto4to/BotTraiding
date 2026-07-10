/**
 * Chart theme — single restrained palette, validated with the dataviz
 * palette checker against surface #0b0e14 (all checks pass):
 * accent #4f46e5 (primary series), green #16a34a (gains only),
 * red #ef4444 (losses/drawdown only), neutral gray grid.
 */

export const chart = {
  accent: "#4f46e5",
  green: "#16a34a",
  red: "#ef4444",
  grid: "#232936",
  axis: "#8b93a3",
  tooltipBg: "#12161f",
  tooltipBorder: "#232936",
  text: "#e2e5ec",
} as const;

export const tooltipStyle = {
  backgroundColor: chart.tooltipBg,
  border: `1px solid ${chart.tooltipBorder}`,
  borderRadius: 6,
  color: chart.text,
  fontSize: 12,
} as const;

export const axisTick = { fill: chart.axis, fontSize: 11 } as const;
