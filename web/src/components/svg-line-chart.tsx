/**
 * SvgLineChart — lightweight SVG line chart with gradient fill.
 * No external chart library — just SVG polyline + gradient.
 */

import { useId, useState } from "react";
import { cn } from "@/lib/utils";

export type ChartPoint = { x: number; y: number; label?: string };

export function SvgLineChart({
  data,
  height = 140,
  color = "var(--color-accent)",
  yMin,
  yMax,
  className,
}: {
  data: ChartPoint[];
  height?: number;
  color?: string;
  yMin?: number;
  yMax?: number;
  className?: string;
}) {
  const gradId = useId();
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (data.length < 2) {
    return (
      <div
        className={cn("flex items-center justify-center text-xs text-faint", className)}
        style={{ height }}
      >
        Not enough data yet
      </div>
    );
  }

  const w = 600;
  const h = height;
  const pad = { top: 8, right: 8, bottom: 18, left: 32 };
  const innerW = w - pad.left - pad.right;
  const innerH = h - pad.top - pad.bottom;

  const xs = data.map((d) => d.x);
  const ys = data.map((d) => d.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yLo = yMin ?? Math.min(...ys);
  const yHi = yMax ?? Math.max(...ys);
  const yRange = yHi - yLo || 1;
  const xRange = xMax - xMin || 1;

  const toX = (x: number) => pad.left + ((x - xMin) / xRange) * innerW;
  const toY = (y: number) => pad.top + innerH - ((y - yLo) / yRange) * innerH;

  const points = data.map((d) => `${toX(d.x)},${toY(d.y)}`).join(" ");
  const areaPoints = `${pad.left},${pad.top + innerH} ${points} ${pad.left + innerW},${pad.top + innerH}`;

  // Y-axis labels (3 ticks)
  const yTicks = [yLo, yLo + yRange * 0.5, yHi];

  return (
    <div className={cn("relative", className)}>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full"
        style={{ height }}
        preserveAspectRatio="none"
        onMouseLeave={() => setHoverIdx(null)}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Y-axis grid lines */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={pad.left}
              x2={pad.left + innerW}
              y1={toY(t)}
              y2={toY(t)}
              stroke="var(--color-border)"
              strokeWidth="1"
              strokeDasharray="2 4"
            />
            <text
              x={pad.left - 4}
              y={toY(t) + 3}
              textAnchor="end"
              className="fill-[var(--color-faint)] font-mono"
              style={{ fontSize: "9px" }}
            >
              {Math.round(t).toLocaleString()}
            </text>
          </g>
        ))}

        {/* Area fill */}
        <polygon points={areaPoints} fill={`url(#${gradId})`} />

        {/* Line */}
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {/* Hover dot */}
        {hoverIdx !== null && (
          <circle
            cx={toX(data[hoverIdx].x)}
            cy={toY(data[hoverIdx].y)}
            r="4"
            fill={color}
            stroke="var(--color-bg)"
            strokeWidth="2"
          />
        )}

        {/* Invisible hover targets */}
        {data.map((d, i) => (
          <rect
            key={i}
            x={toX(d.x) - innerW / data.length / 2}
            y={pad.top}
            width={innerW / data.length}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(i)}
          />
        ))}
      </svg>

      {/* Hover tooltip */}
      {hoverIdx !== null && data[hoverIdx] && (
        <div
          className="pointer-events-none absolute top-0 rounded border border-border bg-elevated px-2 py-1 font-mono text-[10px] text-fg shadow-lg"
          style={{
            left: `${(toX(data[hoverIdx].x) / w) * 100}%`,
            transform: "translateX(-50%)",
          }}
        >
          {data[hoverIdx].label ?? data[hoverIdx].y.toLocaleString()}
        </div>
      )}
    </div>
  );
}
