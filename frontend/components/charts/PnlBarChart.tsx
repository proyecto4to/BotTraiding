"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtMoney } from "@/lib/format";
import { axisTick, chart, tooltipStyle } from "./theme";

export interface PnlSample {
  label: string;
  pnl: number;
}

/** PnL bars: green for gains, red for losses (polarity encoding only). */
export function PnlBarChart({ data, height = 200 }: { data: PnlSample[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={axisTick} stroke={chart.grid} />
        <YAxis
          tick={axisTick}
          stroke={chart.grid}
          width={80}
          tickFormatter={(v: number) => fmtMoney(v)}
          label={{ value: "PnL", angle: -90, position: "insideLeft", fill: chart.axis, fontSize: 11 }}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          cursor={{ fill: "rgba(139, 147, 163, 0.08)" }}
          formatter={(value: number | string) => [fmtMoney(Number(value)), "PnL"]}
        />
        <Bar dataKey="pnl" radius={[4, 4, 0, 0]} isAnimationActive={false} maxBarSize={48}>
          {data.map((entry) => (
            <Cell key={entry.label} fill={entry.pnl >= 0 ? chart.green : chart.red} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
