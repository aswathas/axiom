'use client';

import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceArea,
} from 'recharts';

export default function TrendChart({ trend }) {
  const data = trend.series.map((p) => ({
    date: p.t,
    value: Number(p.v),
    unit: p.unit,
    id: p.id,
  }));

  return (
    <div style={{ height: 220, marginTop: 6 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 22, bottom: 4, left: -14 }}>
          <CartesianGrid stroke="#ece7dc" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: '#8a8a8a' }}
            tickLine={false}
            axisLine={{ stroke: '#ddd8cc' }}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#8a8a8a' }}
            tickLine={false}
            axisLine={{ stroke: '#ddd8cc' }}
            domain={['dataMin - 0.2', 'dataMax + 0.2']}
          />
          <Tooltip
            contentStyle={{
              fontSize: 11,
              borderRadius: 4,
              border: '1px solid #e4dfd2',
              fontFamily: 'ui-monospace, Menlo, monospace',
            }}
            formatter={(v) => [`${v} ${trend.unit}`, trend.display]}
          />
          <ReferenceArea
            y1={trend.ref_low}
            y2={trend.ref_high}
            fill="#2e7d52"
            fillOpacity={0.07}
            stroke="none"
            label={{ value: 'reference range', fontSize: 9, fill: '#2e7d52', position: 'right' }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#c8901e"
            strokeWidth={2.5}
            dot={{ r: 3.5, fill: '#c8901e', strokeWidth: 0 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}