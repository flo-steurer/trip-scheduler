(() => {
  const target = document.querySelector('#chip-history-chart');
  if (!target) return;

  const history = JSON.parse(document.querySelector('#chip-holdings-history').textContent);
  if (!history.length) {
    const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'Balance history will appear after the first chip movement.'; target.append(empty); return;
  }

  const points = history.flatMap((series) => series.points);
  const timestamps = points.map((point) => new Date(point.timestamp).getTime());
  const balances = points.map((point) => point.balance_millis);
  const minimumTime = Math.min(...timestamps);
  const maximumTime = Math.max(...timestamps);
  const maximumBalance = Math.max(...balances, 1000);
  const width = 860; const height = 360;
  const padding = { top: 22, right: 18, bottom: 42, left: 58 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const namespace = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(namespace, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Beer Chip holdings over time');
  svg.classList.add('chip-history-graph');
  const xFor = (timestamp) => maximumTime === minimumTime
    ? padding.left + plotWidth / 2
    : padding.left + ((timestamp - minimumTime) / (maximumTime - minimumTime)) * plotWidth;
  const yFor = (balance) => padding.top + plotHeight - (balance / maximumBalance) * plotHeight;
  const formatChips = (millis) => {
    const value = millis / 1000;
    return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
  };

  [0, 0.25, 0.5, 0.75, 1].forEach((ratio) => {
    const balance = Math.round(maximumBalance * ratio);
    const y = yFor(balance);
    const line = document.createElementNS(namespace, 'line');
    line.setAttribute('x1', padding.left); line.setAttribute('x2', width - padding.right);
    line.setAttribute('y1', y); line.setAttribute('y2', y); line.setAttribute('class', 'chip-history-grid'); svg.append(line);
    const label = document.createElementNS(namespace, 'text');
    label.setAttribute('x', padding.left - 9); label.setAttribute('y', y + 4); label.setAttribute('text-anchor', 'end'); label.setAttribute('class', 'chip-history-axis-label'); label.textContent = formatChips(balance); svg.append(label);
  });

  const dateLabel = (timestamp) => new Date(timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' });
  [minimumTime, maximumTime].forEach((timestamp, index) => {
    const label = document.createElementNS(namespace, 'text');
    label.setAttribute('x', xFor(timestamp)); label.setAttribute('y', height - 13);
    label.setAttribute('text-anchor', index ? 'end' : 'start'); label.setAttribute('class', 'chip-history-axis-label'); label.textContent = dateLabel(timestamp); svg.append(label);
  });

  const colors = ['#007a52', '#e6633d', '#4169a7', '#9b5b9d', '#bd7a16', '#16818b', '#b25850', '#52734e'];
  const legend = document.createElement('ul'); legend.className = 'chip-history-legend';
  history.forEach((series, index) => {
    const color = colors[index] || `hsl(${Math.round(index * 137.508) % 360} 55% 38%)`;
    const path = document.createElementNS(namespace, 'path');
    path.setAttribute('class', 'chip-history-line'); path.setAttribute('stroke', color);
    path.setAttribute('d', series.points.map((point, pointIndex) => {
      const x = xFor(new Date(point.timestamp).getTime());
      const y = yFor(point.balance_millis);
      if (!pointIndex) return `M ${x} ${y}`;
      return `H ${x} V ${y}`;
    }).join(' '));
    const title = document.createElementNS(namespace, 'title'); title.textContent = `${series.name}: ${formatChips(series.points.at(-1).balance_millis)} Beer Chips`; path.append(title); svg.append(path);

    const item = document.createElement('li');
    const swatch = document.createElement('i'); swatch.style.backgroundColor = color;
    const name = document.createElement('span'); name.textContent = series.name;
    const balance = document.createElement('strong'); balance.textContent = `${formatChips(series.points.at(-1).balance_millis)} chips`;
    item.append(swatch, name, balance); legend.append(item);
  });
  target.append(svg, legend);
})();
