"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtMoney } from "@/lib/format";
import { axisTick, chart, tooltipStyle } from "./theme";

export interface EquitySample {
  label: string;
  equity: number;
}

/** Equity over time. Single series, accent color, labeled axes. */
export function EquityCurveChart({
  data,
  height = 260,
}: {
  data: EquitySample[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
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
          width={80}
          tickFormatter={(v: number) => fmtMoney(v)}
          label={{ value: "Equity", angle: -90, position: "insideLeft", fill: chart.axis, fontSize: 11 }}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(value: number | string) => [fmtMoney(Number(value)), "Equity"]}
        />
        <Line
          type="monotone"
          dataKey="equity"
          stroke={chart.accent}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
