'use client';

import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';

const COLORS: Record<string, string> = {
  LOW: '#10B981',
  MEDIUM: '#F59E0B',
  COMPLEX: '#EF4444',
  VERY_COMPLEX: '#7C3AED',
  High: '#EF4444',
  Medium: '#F59E0B',
  Low: '#10B981',
};

interface ComplexityChartProps {
  complexity?: Record<string, number>;
}

export default function ComplexityChart({ complexity }: ComplexityChartProps) {
  if (!complexity) {
    return (
      <div className="text-center py-8">
        <p className="text-gray-500">No complexity data available</p>
      </div>
    );
  }

  const data = Object.entries(complexity)
    .map(([name, value]) => ({
      name,
      value,
    }))
    .filter(item => item.value > 0);

  if (data.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-gray-500">No complexity data to display</p>
      </div>
    );
  }

  const total = data.reduce((sum, item) => sum + item.value, 0);

  // Format label with percentage
  const renderLabel = ({ name, percent }: any) => {
    return `${name}: ${(percent * 100).toFixed(0)}%`;
  };

  return (
    <div>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={renderLabel}
            outerRadius={100}
            fill="#8884d8"
            dataKey="value"
          >
            {data.map((entry, index) => {
              const color = COLORS[entry.name] || COLORS[entry.name.toUpperCase()] || '#999';
              return <Cell key={`cell-${index}`} fill={color} />;
            })}
          </Pie>
          <Tooltip 
            formatter={(value: number) => [value, 'Count']}
            contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
          />
          <Legend 
            verticalAlign="bottom" 
            height={36}
            iconType="circle"
          />
        </PieChart>
      </ResponsiveContainer>
      
      <div className="mt-4 text-center">
        <p className="text-3xl font-bold text-gray-900">{total}</p>
        <p className="text-sm text-gray-600">Total Items</p>
      </div>

      {/* Breakdown List */}
      <div className="mt-6 space-y-2">
        {data.map((item) => {
          const color = COLORS[item.name] || COLORS[item.name.toUpperCase()] || '#999';
          const percentage = ((item.value / total) * 100).toFixed(1);
          
          return (
            <div key={item.name} className="flex items-center justify-between text-sm">
              <div className="flex items-center space-x-2">
                <div 
                  className="w-3 h-3 rounded-full" 
                  style={{ backgroundColor: color }}
                />
                <span className="text-gray-700">{item.name}</span>
              </div>
              <div className="flex items-center space-x-3">
                <span className="text-gray-600">{percentage}%</span>
                <span className="font-semibold text-gray-900">{item.value}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}



