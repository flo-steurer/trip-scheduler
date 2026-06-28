(() => {
  const app = document.querySelector('#market-app');
  if (!app) return;

  let results = JSON.parse(document.querySelector('#initial-market-results').textContent);
  let submitting = false;
  let showSettledWorldCup = false;
  const collapsedMarketSections = new Set();
  const nameInput = document.querySelector('#market-name');
  const state = document.querySelector('#market-state');
  const balance = document.querySelector('#market-balance');
  const storageKey = `trip-scheduler:${app.dataset.tripId}:name`;
  const csrfToken = () => document.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
  const currentName = () => nameInput.value.trim();
  const ownParticipant = () => results.participants.find((person) => person.name.toLocaleLowerCase() === currentName().toLocaleLowerCase());
  const marketUrl = (id) => app.dataset.tradeUrl.replace('/0/', `/${id}/`);
  const formatChips = (millis) => {
    const value = (millis || 0) / 1000;
    return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
  };

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
    const chips = ownParticipant()?.beer_chip_millis ?? 10000;
    balance.textContent = `${formatChips(chips)} Beer Chips`;
  }

  function lineChart(history) {
    const namespace = 'http://www.w3.org/2000/svg';
    const width = 620; const height = 245; const left = 8; const right = width - 48; const top = 10; const bottom = height - 25;
    const svg = document.createElementNS(namespace, 'svg'); svg.classList.add('odds-chart'); svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Yes and No market prices over time');
    const pointFor = (entry, index, outcome) => ({
      x: history.length === 1 ? left : left + (index / (history.length - 1)) * (right - left),
      y: bottom - ((outcome === 'yes' ? entry.yes_odds : 100 - entry.yes_odds) / 100) * (bottom - top),
    });
    [0, 20, 40, 60, 80, 100].forEach((odds) => {
      const y = bottom - (odds / 100) * (bottom - top);
      const line = document.createElementNS(namespace, 'line'); line.setAttribute('x1', left); line.setAttribute('x2', right); line.setAttribute('y1', y); line.setAttribute('y2', y); line.setAttribute('class', 'odds-grid'); svg.append(line);
      const label = document.createElementNS(namespace, 'text'); label.setAttribute('x', right + 9); label.setAttribute('y', y + 4); label.setAttribute('class', 'odds-axis-label'); label.textContent = `${odds}%`; svg.append(label);
    });
    ['yes', 'no'].forEach((outcome) => {
      const path = document.createElementNS(namespace, 'path'); path.setAttribute('class', `${outcome}-odds-line`);
      path.setAttribute('d', history.map((entry, index) => {
        const point = pointFor(entry, index, outcome);
        if (!index) return `M ${point.x} ${point.y}`;
        return `H ${point.x} V ${point.y}`;
      }).join(' ')); svg.append(path);
      const finalEntry = history[history.length - 1];
      const last = pointFor(finalEntry, history.length - 1, outcome);
      const dot = document.createElementNS(namespace, 'circle'); dot.setAttribute('cx', last.x); dot.setAttribute('cy', last.y); dot.setAttribute('r', 5); dot.setAttribute('class', `${outcome}-odds-point`);
      const title = document.createElementNS(namespace, 'title'); title.textContent = `${outcome === 'yes' ? 'Yes' : 'No'}: ${outcome === 'yes' ? finalEntry.yes_odds : 100 - finalEntry.yes_odds}¢`; dot.append(title); svg.append(dot);
    });
    return svg;
  }

  function stakePanel(market) {
    const panel = document.createElement('aside'); panel.className = 'market-stakes';
    const title = document.createElement('h4'); title.textContent = `${market.is_resolved ? 'Final' : 'Open'} positions`;
    panel.append(title);
    if (!market.positions.length) {
      const empty = document.createElement('p'); empty.className = 'market-stakes-empty'; empty.textContent = 'No positions yet.'; panel.append(empty); return panel;
    }
    const list = document.createElement('ul'); list.className = 'market-stakes-list';
    market.positions.forEach((position) => {
      const item = document.createElement('li');
      const top = document.createElement('div'); top.className = 'market-stake-top';
      const name = document.createElement('strong'); name.textContent = position.name;
      const amount = document.createElement('span'); amount.textContent = `${formatChips(position.cost_millis)} spent`;
      top.append(name, amount);
      if (market.is_resolved) {
        const detail = document.createElement('span'); detail.className = 'market-stake-detail';
        detail.textContent = `Payout: ${formatChips(position.payout_millis)} chips${position.payout_millis ? ' · +1 karma' : ''}`;
        item.append(top, detail);
      } else {
        const entries = document.createElement('div'); entries.className = 'market-stake-entries'; entries.style.display = 'grid'; entries.style.gap = '2px'; entries.style.marginTop = '3px'; entries.style.fontSize = '.67rem'; entries.style.fontWeight = '720';
        if (position.yes_shares_millis) {
          const yes = document.createElement('span'); yes.className = 'yes'; yes.style.color = '#078357'; yes.textContent = `Yes ${formatChips(position.yes_shares_millis)} shares @ ${position.yes_entry_odds}¢ → ${market.yes_odds}¢`; entries.append(yes);
        }
        if (position.no_shares_millis) {
          const no = document.createElement('span'); no.className = 'no'; no.style.color = '#b94d48'; no.textContent = `No ${formatChips(position.no_shares_millis)} shares @ ${position.no_entry_odds}¢ → ${market.no_odds}¢`; entries.append(no);
        }
        const scenarios = document.createElement('span'); scenarios.className = 'market-stake-detail';
        const pnl = position.profit_loss_millis >= 0 ? `+${formatChips(position.profit_loss_millis)}` : formatChips(position.profit_loss_millis);
        scenarios.textContent = `Value: ${formatChips(position.mark_value_millis)} chips · P/L: ${pnl} chips`;
        const payout = document.createElement('span'); payout.className = 'market-stake-detail'; payout.textContent = `If Yes: ${formatChips(position.yes_payout_millis)} chips · If No: ${formatChips(position.no_payout_millis)} chips`;
        item.append(top, entries, scenarios, payout);
      }
      list.append(item);
    });
    panel.append(list); return panel;
  }

  function marketCard(market) {
    const card = document.createElement('article'); card.className = `market-card${market.is_resolved ? ' resolved' : ''}`;
    const top = document.createElement('div'); top.className = 'market-card-top';
    const question = document.createElement('h3'); question.textContent = market.question;
    const fixture = market.world_cup;
    const fixtureIsLive = !market.is_resolved && fixture && (
      fixture.status === 'live'
      || (fixture.status === 'scheduled' && new Date(fixture.kickoff_at) <= new Date())
    );
    const status = document.createElement('span'); status.className = `market-status${market.is_resolved ? ' resolved' : ''}${fixtureIsLive ? ' live' : ''}`;
    if (market.is_resolved) status.textContent = fixture?.final_score ? `Final: ${fixture.final_score}` : `Resolved: ${market.resolved_outcome === 'yes' ? 'Yes' : 'No'}`;
    else if (fixture) status.textContent = fixtureIsLive ? `Live${fixture.current_score ? ` · ${fixture.current_score}` : ''}` : fixture.status === 'cancelled' ? 'Cancelled' : 'Upcoming';
    else status.textContent = 'Live';
    top.append(question, status); card.append(top);
    if (fixture) {
      const details = document.createElement('p'); details.className = 'market-fixture-details';
      const kickoff = new Date(fixture.kickoff_at).toLocaleTimeString([], { timeStyle: 'short' });
      details.textContent = `${fixture.home_team} vs ${fixture.away_team} · Kickoff ${kickoff}`;
      card.append(details);
    }
    const prices = document.createElement('div'); prices.className = 'market-prices';
    [['Yes', market.yes_odds, 'yes'], ['No', market.no_odds, 'no']].forEach(([label, odds, kind]) => { const price = document.createElement('span'); price.className = `market-price ${kind}`; price.innerHTML = `<small>${label}</small>${odds}¢`; prices.append(price); });
    const analysis = document.createElement('div'); analysis.className = 'market-analysis';
    const chart = document.createElement('div'); chart.className = 'market-chart';
    const legend = document.createElement('div'); legend.className = 'market-chart-legend';
    [['Yes', market.yes_odds, 'yes'], ['No', market.no_odds, 'no']].forEach(([label, odds, kind]) => { const item = document.createElement('span'); item.className = kind; item.textContent = `${label} ${odds}¢`; legend.append(item); });
    chart.append(legend, lineChart(market.odds_history));
    const chartCaption = document.createElement('div'); chartCaption.className = 'chart-caption'; chartCaption.innerHTML = '<span>Market opened</span><span>Latest trade</span>'; chart.append(chartCaption);
    analysis.append(chart, stakePanel(market));
    card.append(prices, analysis);
    const pool = document.createElement('p'); pool.className = 'market-pool'; pool.textContent = `${formatChips(market.total_chips_millis)} Beer Chips traded`; card.append(pool);
    if (market.is_tradeable) {
      const trade = document.createElement('div'); trade.className = 'market-trade';
      const amount = document.createElement('input'); amount.type = 'number'; amount.min = '0.001'; amount.step = '0.001'; amount.max = formatChips(ownParticipant()?.beer_chip_millis ?? 10000); amount.value = '1'; amount.setAttribute('aria-label', 'Beer Chips to spend');
      const yes = document.createElement('button'); yes.type = 'button'; yes.className = 'market-buy yes'; yes.textContent = 'Buy Yes'; yes.addEventListener('click', () => buyShares(market, 'yes', amount.value));
      const no = document.createElement('button'); no.type = 'button'; no.className = 'market-buy no'; no.textContent = 'Buy No'; no.addEventListener('click', () => buyShares(market, 'no', amount.value));
      trade.append(amount, yes, no); card.append(trade);
    }
    return card;
  }

  function worldCupSort(left, right) {
    const leftLive = left.world_cup.status === 'live';
    const rightLive = right.world_cup.status === 'live';
    if (leftLive !== rightLive) return leftLive ? -1 : 1;
    return new Date(left.world_cup.kickoff_at) - new Date(right.world_cup.kickoff_at) || left.id - right.id;
  }

  function fixtureDateKey(market) {
    const date = new Date(market.world_cup.kickoff_at);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  function fixtureDateLabel(market) {
    return new Date(market.world_cup.kickoff_at).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  }

  function section(key, title) {
    const element = document.createElement('section'); element.className = 'market-section';
    const heading = document.createElement('button'); heading.type = 'button'; heading.className = 'market-section-heading'; heading.textContent = title;
    const content = document.createElement('div'); content.className = 'market-section-content'; content.id = `market-section-${key}`;
    const updateCollapsedState = () => {
      const collapsed = collapsedMarketSections.has(key);
      heading.setAttribute('aria-expanded', String(!collapsed));
      heading.setAttribute('aria-controls', content.id);
      content.hidden = collapsed;
    };
    heading.addEventListener('click', () => {
      if (collapsedMarketSections.has(key)) collapsedMarketSections.delete(key);
      else collapsedMarketSections.add(key);
      updateCollapsedState();
    });
    updateCollapsedState();
    element.append(heading, content);
    return { element, content };
  }

  function appendFixtureDateGroups(target, markets) {
    const groups = new Map();
    markets.slice().sort(worldCupSort).forEach((market) => {
      const key = fixtureDateKey(market);
      const group = groups.get(key) || [];
      group.push(market); groups.set(key, group);
    });
    groups.forEach((marketsForDate) => {
      const group = document.createElement('div'); group.className = 'fixture-date-group';
      const heading = document.createElement('h3'); heading.className = 'fixture-date-title'; heading.textContent = fixtureDateLabel(marketsForDate[0]);
      group.append(heading);
      marketsForDate.forEach((market) => group.append(marketCard(market)));
      target.append(group);
    });
  }

  function renderWorldCupMarkets(board, markets) {
    const { element: worldCup, content } = section('world-cup', 'World Cup');
    const active = markets.filter((market) => !market.is_resolved);
    const settled = markets.filter((market) => market.is_resolved);
    if (active.length) appendFixtureDateGroups(content, active);
    if (settled.length) {
      const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'text-button market-section-toggle';
      toggle.textContent = showSettledWorldCup ? 'Hide settled matches' : `Show ${settled.length} settled match${settled.length === 1 ? '' : 'es'}`;
      toggle.setAttribute('aria-expanded', String(showSettledWorldCup));
      toggle.addEventListener('click', () => { showSettledWorldCup = !showSettledWorldCup; renderMarkets(); });
      content.append(toggle);
      if (showSettledWorldCup) appendFixtureDateGroups(content, settled);
    }
    if (!active.length && !showSettledWorldCup) {
      const empty = document.createElement('p'); empty.className = 'market-section-empty'; empty.textContent = settled.length ? 'All World Cup matches are settled.' : 'World Cup fixtures will appear after the next sync.';
      content.append(empty);
    }
    board.append(worldCup);
  }

  function renderOtherMarkets(board, markets) {
    const { element: other, content } = section('other-markets', 'Other markets');
    const live = markets.filter((market) => !market.is_resolved);
    const resolved = markets.filter((market) => market.is_resolved);
    if (live.length) { const heading = document.createElement('h3'); heading.className = 'market-group-title'; heading.textContent = 'Live'; content.append(heading); live.forEach((market) => content.append(marketCard(market))); }
    if (resolved.length) { const heading = document.createElement('h3'); heading.className = 'market-group-title'; heading.textContent = 'Resolved'; content.append(heading); resolved.forEach((market) => content.append(marketCard(market))); }
    board.append(other);
  }

  function renderMarkets() {
    const board = document.querySelector('#market-board'); board.replaceChildren();
    if (!results.markets.length) {
      const empty = document.createElement('p'); empty.className = 'empty market-empty'; empty.textContent = 'No markets yet. The organizer can create one in Django admin.'; board.append(empty); return;
    }
    const worldCupMarkets = results.markets.filter((market) => market.world_cup);
    const otherMarkets = results.markets.filter((market) => !market.world_cup);
    if (worldCupMarkets.length) renderWorldCupMarkets(board, worldCupMarkets);
    if (otherMarkets.length) renderOtherMarkets(board, otherMarkets);
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
