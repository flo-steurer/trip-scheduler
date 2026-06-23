(() => {
  const target = document.querySelector('#chip-history-chart');
  if (!target) return;

  const history = JSON.parse(document.querySelector('#chip-holdings-history').textContent);
  if (!history.length) {
    const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'Balance history will appear after the first chip movement.'; target.append(empty); return;
  }
  if (!window.echarts) {
    const error = document.createElement('p'); error.className = 'empty'; error.textContent = 'The holdings chart could not be loaded.'; target.append(error); return;
  }

  const colors = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
    '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
    '#bcbd22', '#17becf', '#393b79', '#637939',
  ];
  const formatChips = (value) => {
    const rounded = Math.round(value * 1000) / 1000;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(3).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
  };
  const chart = window.echarts.init(target, null, { renderer: 'canvas' });
  const series = history.map((person, index) => {
    const color = colors[index] || `hsl(${Math.round(index * 137.508) % 360} 55% 38%)`;
    return {
      name: person.name,
      type: 'line',
      step: 'end',
      showSymbol: false,
      smooth: false,
      lineStyle: { width: 3, color },
      itemStyle: { color },
      emphasis: { focus: 'series', lineStyle: { width: 5 } },
      data: person.points.map((point) => [point.timestamp, point.balance_millis / 1000]),
    };
  });

  chart.setOption({
    animationDuration: 450,
    color: colors,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      valueFormatter: (value) => `${formatChips(value)} chips`,
    },
    legend: {
      type: 'scroll',
      top: 0,
      left: 0,
      right: 0,
      selectedMode: true,
    },
    grid: { top: 48, right: 24, bottom: 78, left: 62, containLabel: true },
    toolbox: {
      right: 8,
      top: 25,
      feature: { dataZoom: { yAxisIndex: 'none' }, restore: {}, saveAsImage: {} },
    },
    xAxis: {
      type: 'time',
      axisLabel: { formatter: { month: '{MMM} {d}', day: '{MMM} {d}' } },
      axisPointer: { label: { formatter: ({ value }) => new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) } },
    },
    yAxis: {
      type: 'value',
      name: 'Beer Chips',
      min: 0,
      axisLabel: { formatter: (value) => formatChips(value) },
      splitLine: { lineStyle: { color: '#d9e2da', type: 'dashed' } },
    },
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
      { type: 'slider', height: 18, bottom: 22, filterMode: 'none' },
    ],
    series,
  });

  const resizeObserver = new ResizeObserver(() => chart.resize());
  resizeObserver.observe(target);
})();
