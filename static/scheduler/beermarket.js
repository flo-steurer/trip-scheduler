(() => {
  const app = document.querySelector('#market-app');
  if (!app) return;

  let results = JSON.parse(document.querySelector('#initial-market-results').textContent);
  let submitting = false;
  const nameInput = document.querySelector('#market-name');
  const state = document.querySelector('#market-state');
  const balance = document.querySelector('#market-balance');
  const storageKey = `trip-scheduler:${app.dataset.tripId}:name`;
  const csrfToken = () => document.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
  const currentName = () => nameInput.value.trim();
  const ownParticipant = () => results.participants.find((person) => person.name.toLocaleLowerCase() === currentName().toLocaleLowerCase());
  const marketUrl = (id) => app.dataset.tradeUrl.replace('/0/', `/${id}/`);

  function setState(message, error = false) {
    state.textContent = message;
    state.classList.toggle('error', error);
  }

  async function request(url, payload, method = 'POST') {
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: method === 'GET' ? undefined : JSON.stringify(payload),
    });
    const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
    if (!response.ok) throw new Error(data?.error || `Request failed (HTTP ${response.status}).`);
    return data;
  }

  function renderAccount() {
    const chips = ownParticipant()?.beer_chips ?? 10;
    balance.textContent = `${chips} Beer Chip${chips === 1 ? '' : 's'}`;
  }

  function lineChart(history) {
    const namespace = 'http://www.w3.org/2000/svg';
    const width = 520; const height = 150; const left = 10; const right = width - 10; const top = 10; const bottom = height - 22;
    const svg = document.createElementNS(namespace, 'svg'); svg.classList.add('odds-chart'); svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Yes odds over time');
    [25, 50, 75].forEach((odds) => {
      const y = bottom - (odds / 100) * (bottom - top);
      const line = document.createElementNS(namespace, 'line'); line.setAttribute('x1', left); line.setAttribute('x2', right); line.setAttribute('y1', y); line.setAttribute('y2', y); line.setAttribute('class', 'odds-grid'); svg.append(line);
    });
    const pointFor = (entry, index) => ({
      x: history.length === 1 ? left : left + (index / (history.length - 1)) * (right - left),
      y: bottom - (entry.yes_odds / 100) * (bottom - top),
    });
    const path = document.createElementNS(namespace, 'path'); path.setAttribute('class', 'yes-odds-line');
    path.setAttribute('d', history.map((entry, index) => { const point = pointFor(entry, index); return `${index ? 'L' : 'M'} ${point.x} ${point.y}`; }).join(' ')); svg.append(path);
    history.forEach((entry, index) => {
      const point = pointFor(entry, index); const dot = document.createElementNS(namespace, 'circle'); dot.setAttribute('cx', point.x); dot.setAttribute('cy', point.y); dot.setAttribute('r', index === history.length - 1 ? 4 : 2.5); dot.setAttribute('class', 'odds-point');
      const title = document.createElementNS(namespace, 'title'); title.textContent = `Yes: ${entry.yes_odds}¢`; dot.append(title); svg.append(dot);
    });
    return svg;
  }

  function ownPosition(market) {
    const name = currentName().toLocaleLowerCase();
    return market.positions.find((position) => position.name.toLocaleLowerCase() === name);
  }

  function marketCard(market) {
    const card = document.createElement('article'); card.className = `market-card${market.is_resolved ? ' resolved' : ''}`;
    const top = document.createElement('div'); top.className = 'market-card-top';
    const question = document.createElement('h3'); question.textContent = market.question;
    const status = document.createElement('span'); status.className = `market-status${market.is_resolved ? ' resolved' : ''}`; status.textContent = market.is_resolved ? `Resolved: ${market.resolved_outcome === 'yes' ? 'Yes' : 'No'}` : 'Live';
    top.append(question, status); card.append(top);
    const prices = document.createElement('div'); prices.className = 'market-prices';
    [['Yes', market.yes_odds, 'yes'], ['No', market.no_odds, 'no']].forEach(([label, odds, kind]) => { const price = document.createElement('span'); price.className = `market-price ${kind}`; price.innerHTML = `<small>${label}</small>${odds}¢`; prices.append(price); });
    card.append(prices, lineChart(market.odds_history));
    const chartCaption = document.createElement('div'); chartCaption.className = 'chart-caption'; chartCaption.innerHTML = '<span>Market opened</span><span>Latest trade</span>'; card.append(chartCaption);
    const pool = document.createElement('p'); pool.className = 'market-pool'; pool.textContent = `${market.total_chips} Beer Chip${market.total_chips === 1 ? '' : 's'} in the pool`; card.append(pool);
    const position = ownPosition(market);
    if (position) {
      const summary = document.createElement('p'); summary.className = 'market-position';
      summary.textContent = market.is_resolved ? `Your payout: ${position.payout} Beer Chips${position.payout ? ' · +1 Beer Karma' : ''}` : `Your position: ${position.yes_shares} Yes · ${position.no_shares} No shares`;
      card.append(summary);
    }
    if (!market.is_resolved) {
      const trade = document.createElement('div'); trade.className = 'market-trade';
      const amount = document.createElement('input'); amount.type = 'number'; amount.min = '1'; amount.max = String(ownParticipant()?.beer_chips ?? 10); amount.value = '1'; amount.setAttribute('aria-label', 'Beer Chips to spend');
      const yes = document.createElement('button'); yes.type = 'button'; yes.className = 'market-buy yes'; yes.textContent = 'Buy Yes'; yes.addEventListener('click', () => buyShares(market, 'yes', amount.value));
      const no = document.createElement('button'); no.type = 'button'; no.className = 'market-buy no'; no.textContent = 'Buy No'; no.addEventListener('click', () => buyShares(market, 'no', amount.value));
      trade.append(amount, yes, no); card.append(trade);
    }
    return card;
  }

  function renderMarkets() {
    const board = document.querySelector('#market-board'); board.replaceChildren();
    if (!results.markets.length) {
      const empty = document.createElement('p'); empty.className = 'empty market-empty'; empty.textContent = 'No markets yet. The organizer can create one in Django admin.'; board.append(empty); return;
    }
    const live = results.markets.filter((market) => !market.is_resolved);
    const resolved = results.markets.filter((market) => market.is_resolved);
    if (live.length) { const heading = document.createElement('h3'); heading.className = 'market-group-title'; heading.textContent = 'Live'; board.append(heading); live.forEach((market) => board.append(marketCard(market))); }
    if (resolved.length) { const heading = document.createElement('h3'); heading.className = 'market-group-title'; heading.textContent = 'Resolved'; board.append(heading); resolved.forEach((market) => board.append(marketCard(market))); }
  }

  function render() { renderAccount(); renderMarkets(); }

  async function saveName() {
    if (!currentName()) { setState('Enter your name first.', true); nameInput.focus(); return; }
    if (submitting) return;
    submitting = true; setState('Saving…');
    try {
      const data = await request(app.dataset.participantUrl, { name: currentName() });
      results = data.results; nameInput.value = data.participant.name; localStorage.setItem(storageKey, data.participant.name); render(); setState('Trading desk ready');
    } catch (error) { setState(error.message, true); }
    finally { submitting = false; }
  }

  async function buyShares(market, outcome, chips) {
    if (!currentName()) { setState('Save your name before trading.', true); nameInput.focus(); return; }
    if (submitting) return;
    submitting = true; setState('Buying shares…');
    try {
      const data = await request(marketUrl(market.id), { name: currentName(), outcome, chips });
      results = data.results; render(); setState('Trade complete');
    } catch (error) { setState(error.message, true); }
    finally { submitting = false; }
  }

  async function refreshMarkets() {
    if (submitting) return;
    submitting = true; setState('Refreshing odds…');
    try { const data = await request(app.dataset.resultsUrl, null, 'GET'); results = data.results; render(); setState('Odds refreshed'); }
    catch (error) { setState(error.message, true); }
    finally { submitting = false; }
  }

  document.querySelector('#market-save-name').addEventListener('click', saveName);
  nameInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); saveName(); } });
  document.querySelector('#market-refresh').addEventListener('click', refreshMarkets);
  nameInput.value = localStorage.getItem(storageKey) || '';
  render();
})();
