(() => {
  const app = document.querySelector('#trip-app');
  if (!app) return;

  const initialResults = JSON.parse(document.querySelector('#initial-results').textContent);
  const stateCycle = ['unmarked', 'available', 'maybe', 'unavailable'];
  const nameInput = document.querySelector('#participant-name');
  const minimumAttendanceInput = document.querySelector('#minimum-attendance');
  const minimumAttendanceValue = document.querySelector('#minimum-attendance-value');
  const calendar = document.querySelector('#calendar');
  const saveState = document.querySelector('#save-state');
  const proposalForm = document.querySelector('#proposal-form');
  const proposalState = document.querySelector('#proposal-state');
  const proposalSummary = document.querySelector('#proposal-summary');
  const proposalSubmit = document.querySelector('#proposal-submit');
  const proposalCancel = document.querySelector('#proposal-cancel');
  const storageKey = `trip-scheduler:${app.dataset.tripId}:name`;
  let results = initialResults;
  let submitting = false;
  let editingProposalId = null;

  const csrfToken = () => document.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
  const isoDate = (value) => value.toISOString().slice(0, 10);
  const localDate = (iso) => new Date(`${iso}T12:00:00`);
  const currentName = () => nameInput.value.trim();
  const ownParticipant = () => results.participants.find((person) => person.name.toLocaleLowerCase() === currentName().toLocaleLowerCase());
  const statusFor = (date) => ownParticipant()?.availability[date] || 'unmarked';
  const monthName = (date) => date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  const readableDate = (iso) => localDate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const classStatus = (status) => status === 'unmarked' ? 'unmarked' : status;

  function setSaveState(message, error = false) {
    saveState.textContent = message;
    saveState.classList.toggle('error', error);
  }

  function setProposalState(message, error = false) {
    proposalState.textContent = message;
    proposalState.classList.toggle('error', error);
  }

  function minimumAttendanceLabel(value) {
    return `${value} day${Number(value) === 1 ? '' : 's'}`;
  }

  function renderMinimumAttendance() {
    const value = ownParticipant()?.minimum_attendance_days || 1;
    minimumAttendanceInput.value = value;
    minimumAttendanceValue.textContent = minimumAttendanceLabel(value);
  }

  function setupCollapsibles() {
    document.querySelectorAll('[data-collapsible]').forEach((section) => {
      const key = `trip-scheduler:${app.dataset.tripId}:section:${section.dataset.collapsible}`;
      const savedState = localStorage.getItem(key);
      if (savedState !== null) section.open = savedState === 'open';
      section.addEventListener('toggle', () => {
        localStorage.setItem(key, section.open ? 'open' : 'closed');
      });
    });
  }

  async function request(url, payload, method = 'POST') {
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(payload),
    });
    const isJson = response.headers.get('content-type')?.includes('application/json');
    const data = isJson ? await response.json() : null;
    if (!response.ok) throw new Error(data?.error || `Request failed (HTTP ${response.status}).`);
    if (!data) throw new Error('The server returned an unexpected response.');
    return data;
  }

  function monthStarts() {
    const start = localDate(app.dataset.startDate);
    const end = localDate(app.dataset.endDate);
    const months = [];
    const cursor = new Date(start.getFullYear(), start.getMonth(), 1, 12);
    const finalMonth = new Date(end.getFullYear(), end.getMonth(), 1, 12);
    while (cursor <= finalMonth) {
      months.push(new Date(cursor));
      cursor.setMonth(cursor.getMonth() + 1);
    }
    return months;
  }

  function renderCalendar() {
    calendar.replaceChildren();
    const start = app.dataset.startDate;
    const end = app.dataset.endDate;
    for (const monthStart of monthStarts()) {
      const month = document.createElement('section');
      month.className = 'month';
      const heading = document.createElement('h3');
      heading.textContent = monthName(monthStart);
      month.append(heading);
      const weekday = document.createElement('div');
      weekday.className = 'weekday-row';
      ['M', 'T', 'W', 'T', 'F', 'S', 'S'].forEach((letter) => {
        const item = document.createElement('span'); item.textContent = letter; weekday.append(item);
      });
      month.append(weekday);
      const grid = document.createElement('div');
      grid.className = 'calendar-grid';
      const offset = (monthStart.getDay() + 6) % 7;
      for (let index = 0; index < offset; index += 1) grid.append(document.createElement('span'));
      const lastDay = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0).getDate();
      for (let day = 1; day <= lastDay; day += 1) {
        const value = new Date(monthStart.getFullYear(), monthStart.getMonth(), day, 12);
        const iso = isoDate(value);
        if (iso < start || iso > end) { grid.append(document.createElement('span')); continue; }
        const button = document.createElement('button');
        const status = statusFor(iso);
        button.type = 'button';
        button.className = `date-button ${classStatus(status)}`;
        button.dataset.date = iso;
        button.dataset.status = status;
        button.textContent = day;
        button.setAttribute('aria-label', `${readableDate(iso)}: ${status}`);
        button.addEventListener('click', () => updateDate(iso, status));
        grid.append(button);
      }
      month.append(grid);
      calendar.append(month);
    }
  }

  function badge(label, count, kind) {
    const element = document.createElement('span');
    element.className = `count-badge ${kind}`;
    element.textContent = `${count} ${label}`;
    return element;
  }

  function renderResults() {
    const windows = document.querySelector('#best-windows');
    windows.replaceChildren();
    const topWindows = results.windows.slice(0, 5);
    if (!results.participants.length) {
      const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'Waiting for the first response.'; windows.append(empty);
    }
    topWindows.forEach((window, index) => {
      const card = document.createElement('article'); card.className = 'window-card';
      const rank = document.createElement('span'); rank.className = 'rank'; rank.textContent = String(index + 1).padStart(2, '0');
      const details = document.createElement('div');
      const title = document.createElement('h3');
      title.textContent = `${readableDate(window.start_date)} – ${readableDate(window.end_date)} · ${window.duration_days} days`;
      const scores = document.createElement('div'); scores.className = 'window-scores';
      scores.append(badge('attendance', `${window.attendance_rate}%`, 'available'));
      scores.append(badge('eligible', window.eligible_attendee_count, 'available'));
      scores.append(badge('yes', window.confirmed_count, 'available'));
      if (window.possible_count) scores.append(badge('maybe', window.possible_count, 'maybe'));
      scores.append(badge('available days', window.available_person_days, 'available'));
      if (window.maybe_person_days) scores.append(badge('maybe days', window.maybe_person_days, 'maybe'));
      details.append(title, scores);
      const names = document.createElement('p'); names.className = 'window-names';
      const confirmed = window.confirmed.length ? `In: ${window.confirmed.join(', ')}` : 'No confirmed attendees yet';
      const possible = window.possible.length ? ` · Maybe: ${window.possible.join(', ')}` : '';
      const partial = window.partial.length ? ` · Partial: ${window.partial.map((person) => `${person.name} (${person.available_days} days)`).join(', ')}` : '';
      const belowMinimum = window.below_minimum.length ? ` · Not counted: ${window.below_minimum.map((person) => `${person.name} (${person.available_days} / min ${person.minimum_days} days)`).join(', ')}` : '';
      names.textContent = confirmed + possible + partial + belowMinimum;
      details.append(names); card.append(rank, details); windows.append(card);
    });

    const daily = document.querySelector('#daily-summary'); daily.replaceChildren();
    results.daily.forEach((day) => {
      const cell = document.createElement('article'); cell.className = 'daily-cell';
      const date = document.createElement('span'); date.className = 'daily-date'; date.textContent = readableDate(day.date);
      const total = document.createElement('strong'); total.textContent = `${day.available} available`;
      const maybe = document.createElement('span'); maybe.className = 'daily-maybe'; maybe.textContent = day.maybe ? `${day.maybe} maybe` : '—';
      cell.append(date, total, maybe); daily.append(cell);
    });
    document.querySelector('#participant-count').textContent = `${results.participants.length} participant${results.participants.length === 1 ? '' : 's'}`;
    renderMinimumAttendance();
    renderPeople();
    renderProposals();
  }

  function renderPeople() {
    const target = document.querySelector('#people-calendars'); target.replaceChildren();
    if (!results.participants.length) {
      const empty = document.createElement('p'); empty.className = 'empty people-empty'; empty.textContent = 'Participant calendars will appear here.'; target.append(empty); return;
    }
    const start = localDate(app.dataset.startDate); const end = localDate(app.dataset.endDate);
    results.participants.forEach((person) => {
      const card = document.createElement('article'); card.className = 'person-card';
      const name = document.createElement('h3'); name.textContent = person.name; card.append(name);
      const mini = document.createElement('div'); mini.className = 'mini-calendar';
      for (let cursor = new Date(start); cursor <= end; cursor.setDate(cursor.getDate() + 1)) {
        const iso = isoDate(cursor); const status = person.availability[iso] || 'unmarked';
        const day = document.createElement('span'); day.className = `mini-day ${classStatus(status)}`; day.textContent = cursor.getDate(); day.title = `${readableDate(iso)}: ${status}`; mini.append(day);
      }
      card.append(mini); target.append(card);
    });
  }

  function proposalUrl(id) {
    return `${app.dataset.proposalsUrl}${id}/`;
  }

  function hasUpvoted(proposal) {
    const name = currentName().toLocaleLowerCase();
    return Boolean(name) && proposal.voter_names.some((voter) => voter.toLocaleLowerCase() === name);
  }

  function renderProposals() {
    const board = document.querySelector('#proposal-board');
    board.replaceChildren();
    const voteCount = results.proposals.reduce((total, proposal) => total + proposal.vote_count, 0);
    proposalSummary.textContent = `${results.proposals.length} idea${results.proposals.length === 1 ? '' : 's'} · ${voteCount} upvote${voteCount === 1 ? '' : 's'}`;
    if (!results.proposals.length) {
      const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'No ideas yet — add the first one.'; board.append(empty); return;
    }
    const types = [
      ['destination', 'Destinations'],
      ['stay', 'Villas & stays'],
      ['other', 'Other ideas'],
    ];
    types.forEach(([type, label]) => {
      const proposals = results.proposals.filter((proposal) => proposal.type === type);
      if (!proposals.length) return;
      const group = document.createElement('section'); group.className = 'proposal-group';
      const heading = document.createElement('h3'); heading.textContent = label; group.append(heading);
      const cards = document.createElement('div'); cards.className = 'proposal-cards';
      proposals.forEach((proposal) => cards.append(proposalCard(proposal)));
      group.append(cards); board.append(group);
    });
  }

  function proposalCard(proposal) {
    const card = document.createElement('article'); card.className = 'proposal-card';
    const top = document.createElement('div'); top.className = 'proposal-card-top';
    const title = document.createElement('h4'); title.textContent = proposal.title;
    const count = document.createElement('span'); count.className = 'proposal-vote-count'; count.textContent = `${proposal.vote_count} upvote${proposal.vote_count === 1 ? '' : 's'}`;
    top.append(title, count); card.append(top);
    if (proposal.price) { const price = document.createElement('p'); price.className = 'proposal-price'; price.textContent = proposal.price; card.append(price); }
    if (proposal.note) { const note = document.createElement('p'); note.className = 'proposal-note'; note.textContent = proposal.note; card.append(note); }
    if (proposal.url) {
      const link = document.createElement('a'); link.className = 'proposal-link'; link.href = proposal.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Open link ↗'; card.append(link);
    }
    const meta = document.createElement('p'); meta.className = 'proposal-meta';
    const supporters = proposal.voter_names.length ? `Supported by ${proposal.voter_names.join(', ')}` : 'No upvotes yet';
    meta.textContent = `Added by ${proposal.submitted_by} · ${supporters}`; card.append(meta);
    const actions = document.createElement('div'); actions.className = 'proposal-actions';
    const vote = document.createElement('button'); vote.className = `upvote-button${hasUpvoted(proposal) ? ' voted' : ''}`; vote.type = 'button'; vote.textContent = hasUpvoted(proposal) ? 'Remove upvote' : 'Upvote'; vote.addEventListener('click', () => toggleVote(proposal));
    const edit = document.createElement('button'); edit.className = 'text-button'; edit.type = 'button'; edit.textContent = 'Edit'; edit.addEventListener('click', () => beginEdit(proposal));
    const remove = document.createElement('button'); remove.className = 'text-button danger'; remove.type = 'button'; remove.textContent = 'Delete'; remove.addEventListener('click', () => deleteProposal(proposal));
    actions.append(vote, edit, remove); card.append(actions);
    return card;
  }

  function proposalPayload() {
    return {
      name: currentName(),
      type: document.querySelector('#proposal-type').value,
      title: document.querySelector('#proposal-title').value,
      price: document.querySelector('#proposal-price').value,
      url: document.querySelector('#proposal-url').value,
      note: document.querySelector('#proposal-note').value,
    };
  }

  function resetProposalForm() {
    editingProposalId = null;
    proposalForm.reset();
    proposalSubmit.innerHTML = 'Add idea <span>+</span>';
    proposalCancel.hidden = true;
  }

  function beginEdit(proposal) {
    document.querySelector('#proposal-type').value = proposal.type;
    document.querySelector('#proposal-title').value = proposal.title;
    document.querySelector('#proposal-price').value = proposal.price;
    document.querySelector('#proposal-url').value = proposal.url;
    document.querySelector('#proposal-note').value = proposal.note;
    editingProposalId = proposal.id;
    proposalSubmit.textContent = 'Save changes';
    proposalCancel.hidden = false;
    proposalForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function submitProposal(event) {
    event.preventDefault();
    if (!currentName()) { setProposalState('Save your name before adding an idea.', true); nameInput.focus(); return; }
    if (submitting) return;
    submitting = true; setProposalState(editingProposalId ? 'Saving…' : 'Adding…');
    try {
      const url = editingProposalId ? proposalUrl(editingProposalId) : app.dataset.proposalsUrl;
      const data = await request(url, proposalPayload(), editingProposalId ? 'PATCH' : 'POST');
      results = data.results; resetProposalForm(); renderProposals(); setProposalState('Saved');
    } catch (error) { setProposalState(error.message, true); }
    finally { submitting = false; }
  }

  async function toggleVote(proposal) {
    if (!currentName()) { setProposalState('Save your name before voting.', true); nameInput.focus(); return; }
    if (submitting) return;
    submitting = true; setProposalState('Saving…');
    try {
      const data = await request(`${proposalUrl(proposal.id)}vote/`, { name: currentName() });
      results = data.results; renderProposals(); setProposalState('Saved');
    } catch (error) { setProposalState(error.message, true); }
    finally { submitting = false; }
  }

  async function deleteProposal(proposal) {
    if (!currentName()) { setProposalState('Save your name before deleting an idea.', true); nameInput.focus(); return; }
    if (!window.confirm(`Delete “${proposal.title}”?`)) return;
    if (submitting) return;
    submitting = true; setProposalState('Deleting…');
    try {
      const data = await request(proposalUrl(proposal.id), { name: currentName() }, 'DELETE');
      results = data.results;
      if (editingProposalId === proposal.id) resetProposalForm();
      renderProposals(); setProposalState('Deleted');
    } catch (error) { setProposalState(error.message, true); }
    finally { submitting = false; }
  }

  async function saveName() {
    const name = currentName();
    if (!name) { setSaveState('Enter your name first.', true); nameInput.focus(); return false; }
    if (submitting) return false;
    submitting = true; setSaveState('Saving…');
    try {
      const data = await request(app.dataset.participantUrl, { name });
      nameInput.value = data.participant.name;
      localStorage.setItem(storageKey, data.participant.name);
      results = data.results;
      renderCalendar(); renderResults(); setSaveState('Saved');
      return true;
    } catch (error) { setSaveState(error.message, true); return false; }
    finally { submitting = false; }
  }

  async function updateDate(date, currentStatus) {
    const name = currentName();
    if (!name) { setSaveState('Enter and save your name before marking dates.', true); nameInput.focus(); return; }
    if (submitting) return;
    const nextStatus = stateCycle[(stateCycle.indexOf(currentStatus) + 1) % stateCycle.length];
    submitting = true; setSaveState('Saving…');
    try {
      const data = await request(app.dataset.availabilityUrl, { name, date, status: nextStatus });
      nameInput.value = data.participant.name;
      localStorage.setItem(storageKey, data.participant.name);
      results = data.results;
      renderCalendar(); renderResults(); setSaveState('Saved');
    } catch (error) { setSaveState(error.message, true); }
    finally { submitting = false; }
  }

  async function updateMinimumAttendance() {
    const name = currentName();
    if (!name) {
      setSaveState('Save your name before choosing a minimum.', true);
      renderMinimumAttendance();
      nameInput.focus();
      return;
    }
    if (submitting) return;
    submitting = true; setSaveState('Saving…');
    try {
      const data = await request(app.dataset.participantUrl, {
        name,
        minimum_attendance_days: Number(minimumAttendanceInput.value),
      });
      nameInput.value = data.participant.name;
      localStorage.setItem(storageKey, data.participant.name);
      results = data.results;
      renderCalendar(); renderResults(); setSaveState('Saved');
    } catch (error) {
      setSaveState(error.message, true);
      renderMinimumAttendance();
    } finally { submitting = false; }
  }

  document.querySelector('#save-name').addEventListener('click', saveName);
  nameInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); saveName(); } });
  minimumAttendanceInput.addEventListener('input', () => { minimumAttendanceValue.textContent = minimumAttendanceLabel(minimumAttendanceInput.value); });
  minimumAttendanceInput.addEventListener('change', updateMinimumAttendance);
  proposalForm.addEventListener('submit', submitProposal);
  proposalCancel.addEventListener('click', resetProposalForm);
  document.querySelector('#copy-link').addEventListener('click', async (event) => {
    const input = document.querySelector('#share-url');
    try { await navigator.clipboard.writeText(input.value); event.currentTarget.textContent = 'Copied'; }
    catch (_) { input.select(); document.execCommand('copy'); event.currentTarget.textContent = 'Copied'; }
    window.setTimeout(() => { event.currentTarget.textContent = 'Copy'; }, 1600);
  });

  nameInput.value = localStorage.getItem(storageKey) || '';
  setupCollapsibles();
  renderCalendar(); renderResults();
})();
