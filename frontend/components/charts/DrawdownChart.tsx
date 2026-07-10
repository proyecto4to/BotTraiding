"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtPct } from "@/lib/format";
import { axisTick, chart, tooltipStyle } from "./theme";

export interface DrawdownSample {
  label: string;
  drawdown: number; // fraction, 0.05 = 5% below peak
}

/** Drawdown over time — red (losses) only, plotted downward from zero. */
export function DrawdownChart({
  data,
  height = 200,
}: {
  data: DrawdownSample[];
  height?: number;
}) {
  const plotted = data.map((d) => ({ ...d, dd: -Math.abs(d.drawdown) }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={plotted} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="label"
          tick={axisTick}
          stroke={chart.grid}
          label={{ value: "Time", position: "insideBottom", offset: -2, fill: chart.axis, fontSize: 11 }}
        />
        <YAxis
          tick={axisTick}
          stroke={chart.grid}
          width={64}
          tickFormatter={(v: number) => fmtPct(v, 1)}
          label={{ value: "Drawdown", angle: -90, position: "insideLeft", fill: chart.axis, fontSize: 11 }}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(value: number | string) => [fmtPct(Math.abs(Number(value))), "Drawdown"]}
        />
        <Area
          type="monotone"
          dataKey="dd"
          stroke={chart.red}
          strokeWidth={2}
          fill={chart.red}
          fillOpacity={0.15}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
