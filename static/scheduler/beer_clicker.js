(() => {
  const app = document.querySelector('#clicker-app');
  if (!app) return;

  const nameInput = document.querySelector('#clicker-name');
  const saveName = document.querySelector('#clicker-save-name');
  const clickButton = document.querySelector('#beer-click-button');
  const convertButton = document.querySelector('#clicker-convert');
  const state = document.querySelector('#clicker-state');
  const conversionStatus = document.querySelector('#clicker-conversion-status');
  const storageKey = `trip-scheduler:${app.dataset.tripId}:name`;
  let account = null;
  let leaderboard = [];
  let busy = false;
  const csrfToken = () => document.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
  const currentName = () => nameInput.value.trim();
  const formatChips = (millis) => {
    const value = (millis || 0) / 1000;
    return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
  };

  async function request(url) {
    const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() }, body: JSON.stringify({ name: currentName() }) });
    const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
    if (!response.ok) {
      const error = new Error(data?.error || `Request failed (HTTP ${response.status}).`);
      error.data = data;
      throw error;
    }
    return data;
  }

  function setState(message, error = false) {
    state.textContent = message;
    state.classList.toggle('error', error);
  }

  function renderLeaderboard(entries) {
    const list = document.querySelector('#clicker-leaderboard-list');
    list.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement('li'); empty.className = 'empty'; empty.textContent = 'No one has joined this trip yet. Start the tap.'; list.append(empty); return;
    }
    entries.forEach((entry) => {
      const item = document.createElement('li'); item.className = `leaderboard-entry${entry.rank === 1 ? ' leaderboard-leader' : ''}`;
      const rank = document.createElement('span'); rank.className = 'leaderboard-rank'; rank.textContent = entry.rank === 1 ? '👑' : entry.rank;
      const person = document.createElement('div'); person.className = 'leaderboard-person';
      const name = document.createElement('strong'); name.textContent = entry.name;
      const balance = document.createElement('span'); balance.textContent = `${entry.clicker_balance} available`;
      const score = document.createElement('strong'); score.className = 'karma-score'; score.append(`${entry.lifetime_earned} `);
      const suffix = document.createElement('span'); suffix.textContent = 'earned'; score.append(suffix);
      person.append(name, balance); item.append(rank, person, score); list.append(item);
    });
  }

  function render(data) {
    account = data.account;
    leaderboard = data.leaderboard;
    document.querySelector('#clicker-balance').textContent = account.clicker_balance;
    document.querySelector('#clicker-lifetime').textContent = account.lifetime_earned;
    document.querySelector('#clicker-rate').textContent = `${account.conversion_rate_units} clicker currency = 1 Beer Chip. You can convert up to ${formatChips(account.daily_conversion_cap_millis)} Beer Chips each UTC day.`;
    document.querySelector('#clicker-allowance').textContent = `Today’s remaining allowance: ${formatChips(account.remaining_daily_conversion_millis)} Beer Chips · ${formatChips(account.available_conversion_millis)} currently available to convert`;
    clickButton.disabled = busy || !currentName();
    convertButton.disabled = busy || !currentName() || !account.available_conversion_millis;
    renderLeaderboard(leaderboard);
  }

  function showFloater() {
    const floater = document.createElement('span'); floater.textContent = '+1'; document.querySelector('#clicker-floaters').append(floater);
    floater.addEventListener('animationend', () => floater.remove());
  }

  async function saveAccount() {
    if (!currentName()) { setState('Enter your name first.', true); return; }
    busy = true; setState('Loading your tap…');
    try {
      const data = await request(app.dataset.statusUrl);
      localStorage.setItem(storageKey, currentName()); render(data); setState('Ready to click.');
    } catch (error) { setState(error.message, true); } finally { busy = false; if (account) render({ account, leaderboard }); }
  }

  saveName.addEventListener('click', saveAccount);
  nameInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') saveAccount(); });
  clickButton.addEventListener('click', async () => {
    if (busy || !currentName()) return;
    busy = true; clickButton.disabled = true;
    try {
      const data = await request(app.dataset.clickUrl); render(data); showFloater(); setState('+1 clicker currency');
    } catch (error) {
      if (error.data?.account) { render(error.data); window.setTimeout(() => { if (account) render({ account, leaderboard }); }, error.data.retry_after_ms || 1000); }
      setState(error.message, true);
    } finally { busy = false; if (account) render({ account, leaderboard }); }
  });
  convertButton.addEventListener('click', async () => {
    if (busy || !currentName()) return;
    busy = true; convertButton.disabled = true;
    try {
      const data = await request(app.dataset.convertUrl); render(data);
      conversionStatus.textContent = data.credited_millis ? `Converted ${formatChips(data.credited_millis)} Beer Chips.` : 'Nothing more can be converted right now.';
    } catch (error) { conversionStatus.textContent = error.message; conversionStatus.classList.add('error'); } finally { busy = false; if (account) render({ account, leaderboard }); }
  });

  const savedName = localStorage.getItem(storageKey);
  if (savedName) { nameInput.value = savedName; saveAccount(); }
})();
