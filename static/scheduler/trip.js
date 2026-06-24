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
  const proposalType = document.querySelector('#proposal-type');
  const stayDetails = document.querySelector('#stay-details');
  const proposalTypeHint = document.querySelector('#proposal-type-hint');
  const proposalPriceField = document.querySelector('#proposal-price-field');
  const proposalTitle = document.querySelector('#proposal-title');
  const storageKey = `trip-scheduler:${app.dataset.tripId}:name`;
  let results = initialResults;
  let submitting = false;
  let editingProposalId = null;
  let rangeGesture = null;
  let suppressNextCalendarClick = false;

  const csrfToken = () => document.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
  const isoDate = (value) => value.toISOString().slice(0, 10);
  const localDate = (iso) => new Date(`${iso}T12:00:00`);
  const currentName = () => nameInput.value.trim();
  const ownParticipant = () => results.participants.find((person) => person.name.toLocaleLowerCase() === currentName().toLocaleLowerCase());
  const formatChips = (millis) => {
    const chips = (millis ?? 0) / 1000;
    return Number.isInteger(chips) ? String(chips) : chips.toFixed(3).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
  };
  const formatMoney = (amount, currency) => {
    if (amount === null || amount === undefined || amount === '') return '';
    try {
      return new Intl.NumberFormat(undefined, {
        style: currency ? 'currency' : 'decimal', currency: currency || undefined,
        maximumFractionDigits: 2,
      }).format(Number(amount));
    } catch (_) { return `${amount}${currency ? ` ${currency}` : ''}`; }
  };
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

  function nextStatus(status) {
    return stateCycle[(stateCycle.indexOf(status) + 1) % stateCycle.length];
  }

  function dateAtPoint(clientX, clientY) {
    return document.elementFromPoint(clientX, clientY)?.closest('.date-button')?.dataset.date || null;
  }

  function previewRange(startDate, endDate) {
    const first = startDate < endDate ? startDate : endDate;
    const last = startDate < endDate ? endDate : startDate;
    document.querySelectorAll('.date-button').forEach((button) => {
      button.classList.toggle('range-preview', button.dataset.date >= first && button.dataset.date <= last);
    });
  }

  function clearRangePreview() {
    document.querySelectorAll('.date-button.range-preview').forEach((button) => button.classList.remove('range-preview'));
  }

  function startRangeGesture(event, startDate) {
    if (submitting || (event.pointerType === 'mouse' && event.button !== 0)) return;
    rangeGesture = {
      pointerId: event.pointerId,
      pointerType: event.pointerType,
      startDate,
      endDate: startDate,
      startX: event.clientX,
      startY: event.clientY,
      active: false,
      timer: null,
    };
    if (event.pointerType === 'touch') {
      rangeGesture.timer = window.setTimeout(() => {
        if (!rangeGesture || rangeGesture.pointerId !== event.pointerId) return;
        rangeGesture.active = true;
        previewRange(rangeGesture.startDate, rangeGesture.endDate);
        setSaveState('Drag across dates, then release to apply.');
      }, 350);
    }
  }

  function finishRangeGesture(event, cancelled = false) {
    if (!rangeGesture || rangeGesture.pointerId !== event.pointerId) return;
    window.clearTimeout(rangeGesture.timer);
    const gesture = rangeGesture;
    rangeGesture = null;
    if (!gesture.active || cancelled) { clearRangePreview(); return; }
    suppressNextCalendarClick = true;
    window.setTimeout(() => { suppressNextCalendarClick = false; }, 0);
    clearRangePreview();
    updateDateRange(gesture.startDate, gesture.endDate);
  }

  function handleRangePointerMove(event) {
    if (!rangeGesture || rangeGesture.pointerId !== event.pointerId) return;
    const selectedDate = dateAtPoint(event.clientX, event.clientY);
    const movedEnough = Math.hypot(event.clientX - rangeGesture.startX, event.clientY - rangeGesture.startY) > 10;
    if (!rangeGesture.active) {
      if (rangeGesture.pointerType === 'touch' && movedEnough) {
        window.clearTimeout(rangeGesture.timer);
        if (selectedDate && selectedDate !== rangeGesture.startDate) {
          rangeGesture.active = true;
          setSaveState('Release to apply this range.');
        }
      }
      if (rangeGesture.pointerType !== 'touch' && selectedDate && selectedDate !== rangeGesture.startDate) {
        rangeGesture.active = true;
        setSaveState('Release to apply this range.');
      }
    }
    if (!rangeGesture?.active || !selectedDate) return;
    rangeGesture.endDate = selectedDate;
    previewRange(rangeGesture.startDate, selectedDate);
    event.preventDefault();
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
        button.addEventListener('pointerdown', (event) => startRangeGesture(event, iso));
        button.addEventListener('click', (event) => {
          if (suppressNextCalendarClick) {
            suppressNextCalendarClick = false;
            event.preventDefault();
            return;
          }
          updateDate(iso, status);
        });
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

  function metricBadge(text, kind) {
    const element = document.createElement('span');
    element.className = `count-badge ${kind}`;
    element.textContent = text;
    return element;
  }

  function attendanceLine(label, values, kind) {
    const line = document.createElement('div'); line.className = `attendance-line ${kind}`;
    const labelElement = document.createElement('span'); labelElement.className = 'attendance-label'; labelElement.textContent = label;
    const valuesElement = document.createElement('span'); valuesElement.className = 'attendance-values'; valuesElement.textContent = values.join(', ');
    line.append(labelElement, valuesElement);
    return line;
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
      const villaRange = window.minimum_villa_occupancy === window.maximum_villa_capacity
        ? `${window.maximum_villa_capacity} possible guests/day`
        : `${window.minimum_villa_occupancy}–${window.maximum_villa_capacity} possible guests/day`;
      scores.append(metricBadge(villaRange, 'villa'));
      scores.append(metricBadge(`${window.average_villa_fill}% filled`, 'villa'));
      details.append(title, scores);
      const breakdown = document.createElement('div'); breakdown.className = 'attendance-breakdown';
      if (window.confirmed.length) breakdown.append(attendanceLine(`Confirmed (${window.confirmed_count})`, window.confirmed, 'confirmed'));
      if (window.possible.length) breakdown.append(attendanceLine(`Maybe (${window.possible_count})`, window.possible, 'maybe'));
      if (window.partial.length) breakdown.append(attendanceLine(`Partial (${window.partial.length})`, window.partial.map((person) => `${person.name} · ${person.available_days} days`), 'partial'));
      if (window.below_minimum.length) breakdown.append(attendanceLine(`Not counted (${window.below_minimum.length})`, window.below_minimum.map((person) => `${person.name} · ${person.available_days}/${person.minimum_days} days`), 'excluded'));
      if (!breakdown.children.length) breakdown.append(attendanceLine('Attendance', ['No eligible attendees yet'], 'excluded'));
      details.append(breakdown); card.append(rank, details); windows.append(card);
    });

    const daily = document.querySelector('#daily-summary'); daily.replaceChildren();
    results.daily.forEach((day) => {
      const cell = document.createElement('article'); cell.className = 'daily-cell';
      const date = document.createElement('span'); date.className = 'daily-date'; date.textContent = readableDate(day.date);
      const total = document.createElement('strong'); total.textContent = `${day.available} available`;
      const maybe = document.createElement('span'); maybe.className = 'daily-maybe'; maybe.textContent = day.maybe ? `${day.maybe} maybe` : '—';
      cell.append(date, total, maybe); daily.append(cell);
    });
    const activeCount = results.active_participant_count;
    document.querySelector('#participant-count').textContent = `${activeCount} active participant${activeCount === 1 ? '' : 's'}`;
    renderMinimumAttendance();
    renderPeople();
    renderProposals();
  }

  function renderPeople() {
    const target = document.querySelector('#people-calendars'); target.replaceChildren();
    const activeParticipants = results.participants.filter((person) => person.is_active);
    if (!activeParticipants.length) {
      const empty = document.createElement('p'); empty.className = 'empty people-empty'; empty.textContent = 'Active participant calendars will appear once someone marks a date.'; target.append(empty); return;
    }
    const start = localDate(app.dataset.startDate); const end = localDate(app.dataset.endDate);
    activeParticipants.forEach((person) => {
      const card = document.createElement('article'); card.className = 'person-card';
      const heading = document.createElement('div'); heading.className = 'person-card-heading';
      const name = document.createElement('h3'); name.textContent = person.name;
      const chips = formatChips(person.beer_chip_millis);
      const karma = document.createElement('span'); karma.className = 'person-karma'; karma.textContent = `✦ ${person.beer_karma || 0} · ${chips} chips`; karma.title = `${person.beer_karma || 0} Beer Karma · ${chips} Beer Chips`;
      heading.append(name, karma); card.append(heading);
      const minimum = document.createElement('p'); minimum.className = 'participant-minimum'; minimum.textContent = `Minimum: ${minimumAttendanceLabel(person.minimum_attendance_days)}`; card.append(minimum);
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
      if (type === 'stay') group.append(villaComparison(proposals));
      const cards = document.createElement('div'); cards.className = 'proposal-cards';
      proposals.forEach((proposal) => cards.append(proposalCard(proposal)));
      group.append(cards); board.append(group);
    });
  }

  function stayCapacityKind(proposal) {
    const topWindow = results.windows[0];
    if (!proposal.sleeps || !topWindow || proposal.sleeps >= topWindow.maximum_villa_capacity) return '';
    return proposal.sleeps < topWindow.maximum_confirmed_villa_capacity
      ? 'confirmed-shortfall'
      : 'possible-shortfall';
  }

  function villaComparison(proposals) {
    const comparable = proposals.filter((proposal) => proposal.total_price !== null || proposal.sleeps || proposal.bedrooms || proposal.location);
    if (!comparable.length) return document.createDocumentFragment();
    const wrap = document.createElement('div'); wrap.className = 'villa-comparison-wrap';
    const intro = document.createElement('p'); intro.className = 'villa-comparison-note';
    const topCapacity = results.windows[0]?.maximum_villa_capacity || 0;
    intro.textContent = topCapacity
      ? `Per-person cost uses the top range’s peak of ${topCapacity} possible guest${topCapacity === 1 ? '' : 's'}, capped at each villa’s Sleeps value.`
      : 'Per-person cost will appear once a possible trip range is available.';
    const capacityKinds = proposals.map(stayCapacityKind);
    if (capacityKinds.some(Boolean)) {
      const legend = document.createElement('p'); legend.className = 'villa-capacity-legend';
      if (capacityKinds.includes('confirmed-shortfall')) {
        const confirmed = document.createElement('span'); confirmed.className = 'confirmed-shortfall'; confirmed.textContent = 'Confirmed shortfall'; legend.append(confirmed);
      }
      if (capacityKinds.includes('possible-shortfall')) {
        const possible = document.createElement('span'); possible.className = 'possible-shortfall'; possible.textContent = 'Possible shortfall'; legend.append(possible);
      }
      wrap.append(intro, legend);
    } else {
      wrap.append(intro);
    }
    const table = document.createElement('table'); table.className = 'villa-comparison';
    const head = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['Villa', 'Total', 'Per person', 'Beds', 'Location', 'Would book'].forEach((label) => { const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = label; headRow.append(cell); });
    head.append(headRow); table.append(head);
    const body = document.createElement('tbody');
    comparable.forEach((proposal) => {
      const row = document.createElement('tr');
      const capacityKind = stayCapacityKind(proposal);
      const cells = [
        proposal.title,
        formatMoney(proposal.total_price, proposal.currency) || '—',
        formatMoney(proposal.price_per_best_window_person, proposal.currency) || '—',
        proposal.sleeps ? `${proposal.sleeps} sleeps${proposal.bedrooms ? ` · ${proposal.bedrooms} BR` : ''}` : (proposal.bedrooms ? `${proposal.bedrooms} BR` : '—'),
        proposal.location || '—',
        `${proposal.booking_count} interested`,
      ];
      cells.forEach((value, index) => {
        const cell = document.createElement('td'); cell.textContent = value;
        if (index === 3 && capacityKind) {
          cell.className = `villa-capacity-cell ${capacityKind}`;
          cell.title = capacityKind === 'confirmed-shortfall'
            ? 'Too small for confirmed guests in the top date range.'
            : 'May be too small when Maybe guests join the top date range.';
        }
        row.append(cell);
      });
      body.append(row);
    });
    table.append(body); wrap.append(table); return wrap;
  }

  function proposalCard(proposal) {
    const card = document.createElement('article'); card.className = 'proposal-card';
    const top = document.createElement('div'); top.className = 'proposal-card-top';
    const title = document.createElement('h4'); title.textContent = proposal.title;
    const count = document.createElement('span'); count.className = 'proposal-vote-count'; count.textContent = `${proposal.vote_count} upvote${proposal.vote_count === 1 ? '' : 's'}`;
    top.append(title, count); card.append(top);
    if (proposal.type === 'stay') {
      const details = [];
      if (proposal.location) details.push(proposal.location);
      if (proposal.sleeps) details.push(`Sleeps ${proposal.sleeps}`);
      if (proposal.bedrooms) details.push(`${proposal.bedrooms} bedroom${proposal.bedrooms === 1 ? '' : 's'}`);
      if (details.length) { const detail = document.createElement('p'); detail.className = 'villa-details'; detail.textContent = details.join(' · '); card.append(detail); }
      if (proposal.total_price !== null) {
        const cost = document.createElement('p'); cost.className = 'proposal-price';
        const perPerson = formatMoney(proposal.price_per_best_window_person, proposal.currency);
        cost.textContent = `${formatMoney(proposal.total_price, proposal.currency)} total${perPerson ? ` · ${perPerson} per active person` : ''}`;
        card.append(cost);
      }
      if (proposal.cancellation_terms) { const cancellation = document.createElement('p'); cancellation.className = 'villa-cancellation'; cancellation.textContent = `Cancellation: ${proposal.cancellation_terms}`; card.append(cancellation); }
      const interest = document.createElement('p'); interest.className = 'booking-interest-summary';
      const interested = proposal.booking_names.length ? proposal.booking_names.join(', ') : 'No one yet';
      interest.textContent = `Interested (non-binding): ${interested}`; card.append(interest);
    }
    if (proposal.price) { const price = document.createElement('p'); price.className = 'proposal-price'; price.textContent = proposal.price; card.append(price); }
    if (proposal.note) { const note = document.createElement('p'); note.className = 'proposal-note'; note.textContent = proposal.note; card.append(note); }
    if (proposal.url) {
      const link = document.createElement('a'); link.className = 'proposal-link'; link.href = proposal.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Open link ↗'; card.append(link);
    }
    const meta = document.createElement('p'); meta.className = 'proposal-meta';
    const supporters = proposal.voter_names.length ? `Supported by ${proposal.voter_names.join(', ')}` : 'No upvotes yet';
    meta.textContent = `Added by ${proposal.submitted_by} · ${supporters}`; card.append(meta);
    const actions = document.createElement('div'); actions.className = 'proposal-actions';
    const vote = document.createElement('button'); const voted = hasUpvoted(proposal); vote.className = `upvote-button${voted ? ' voted' : ''}`; vote.type = 'button'; vote.textContent = voted ? 'Upvoted ✓' : 'Upvote'; vote.title = voted ? 'Remove your upvote' : 'Upvote this idea'; vote.setAttribute('aria-pressed', String(voted)); vote.addEventListener('click', () => toggleVote(proposal));
    actions.append(vote);
    if (proposal.type === 'stay') {
      const booking = document.createElement('button'); const hasInterest = hasBookingInterest(proposal);
      booking.className = `booking-button${hasInterest ? ' interested' : ''}`; booking.type = 'button';
      booking.textContent = hasInterest ? 'Interested ✓' : 'I’m interested';
      booking.title = hasInterest ? 'Remove your non-binding interest' : 'Mark that you are interested in this stay';
      booking.setAttribute('aria-pressed', String(hasInterest));
      booking.addEventListener('click', () => toggleBookingInterest(proposal)); actions.append(booking);
    }
    const secondaryActions = document.createElement('div'); secondaryActions.className = 'proposal-secondary-actions';
    const edit = document.createElement('button'); edit.className = 'text-button'; edit.type = 'button'; edit.textContent = 'Edit'; edit.addEventListener('click', () => beginEdit(proposal));
    const remove = document.createElement('button'); remove.className = 'text-button danger'; remove.type = 'button'; remove.textContent = 'Delete'; remove.addEventListener('click', () => deleteProposal(proposal));
    secondaryActions.append(edit, remove); actions.append(secondaryActions); card.append(actions);
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
      total_price: document.querySelector('#proposal-total-price').value,
      currency: document.querySelector('#proposal-currency').value,
      location: document.querySelector('#proposal-location').value,
      bedrooms: document.querySelector('#proposal-bedrooms').value,
      sleeps: document.querySelector('#proposal-sleeps').value,
      cancellation_terms: document.querySelector('#proposal-cancellation-terms').value,
    };
  }

  function resetProposalForm() {
    editingProposalId = null;
    proposalForm.reset();
    updateStayDetails();
    proposalSubmit.innerHTML = 'Add idea <span>+</span>';
    proposalCancel.hidden = true;
  }

  function beginEdit(proposal) {
    document.querySelector('#proposal-type').value = proposal.type;
    document.querySelector('#proposal-title').value = proposal.title;
    document.querySelector('#proposal-price').value = proposal.price;
    document.querySelector('#proposal-url').value = proposal.url;
    document.querySelector('#proposal-note').value = proposal.note;
    document.querySelector('#proposal-total-price').value = proposal.total_price ?? '';
    document.querySelector('#proposal-currency').value = proposal.currency;
    document.querySelector('#proposal-location').value = proposal.location;
    document.querySelector('#proposal-bedrooms').value = proposal.bedrooms ?? '';
    document.querySelector('#proposal-sleeps').value = proposal.sleeps ?? '';
    document.querySelector('#proposal-cancellation-terms').value = proposal.cancellation_terms;
    updateStayDetails();
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
      results = data.results; resetProposalForm(); renderResults(); setProposalState('Saved');
    } catch (error) { setProposalState(error.message, true); }
    finally { submitting = false; }
  }

  async function toggleVote(proposal) {
    if (!currentName()) { setProposalState('Save your name before voting.', true); nameInput.focus(); return; }
    if (submitting) return;
    submitting = true; setProposalState('Saving…');
    try {
      const data = await request(`${proposalUrl(proposal.id)}vote/`, { name: currentName() });
      results = data.results; renderResults(); setProposalState('Saved');
    } catch (error) { setProposalState(error.message, true); }
    finally { submitting = false; }
  }

  function hasBookingInterest(proposal) {
    const name = currentName().toLocaleLowerCase();
    return Boolean(name) && proposal.booking_names.some((person) => person.toLocaleLowerCase() === name);
  }

  async function toggleBookingInterest(proposal) {
    if (!currentName()) { setProposalState('Save your name before marking a stay.', true); nameInput.focus(); return; }
    if (submitting) return;
    submitting = true; setProposalState('Saving…');
    try {
      const data = await request(`${proposalUrl(proposal.id)}booking-interest/`, { name: currentName() });
      results = data.results; renderResults(); setProposalState('Saved');
    } catch (error) { setProposalState(error.message, true); }
    finally { submitting = false; }
  }

  function updateStayDetails() {
    const isStay = proposalType.value === 'stay';
    stayDetails.hidden = !isStay;
    proposalPriceField.hidden = !isStay;
    const copy = {
      destination: {
        hint: 'Suggest a place or region for the trip. Add a link and why it is a good fit.',
        placeholder: 'e.g. Istrian coast',
      },
      stay: {
        hint: 'Compare villas by total cost, beds, location, cancellation terms, and who would book.',
        placeholder: 'e.g. Villa overlooking Lake Garda',
      },
      other: {
        hint: 'Add anything that helps the group decide or organise the trip.',
        placeholder: 'e.g. Ask Luca about his boat',
      },
    }[proposalType.value];
    proposalTypeHint.textContent = copy.hint;
    proposalTitle.placeholder = copy.placeholder;
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
      renderResults(); setProposalState('Deleted');
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
    const newStatus = nextStatus(currentStatus);
    submitting = true; setSaveState('Saving…');
    try {
      const data = await request(app.dataset.availabilityUrl, { name, date, status: newStatus });
      nameInput.value = data.participant.name;
      localStorage.setItem(storageKey, data.participant.name);
      results = data.results;
      renderCalendar(); renderResults(); setSaveState('Saved');
    } catch (error) { setSaveState(error.message, true); }
    finally { submitting = false; }
  }

  async function updateDateRange(startDate, endDate) {
    const name = currentName();
    if (!name) { setSaveState('Enter and save your name before marking dates.', true); nameInput.focus(); return; }
    if (submitting) return;
    const rangeStart = startDate < endDate ? startDate : endDate;
    const rangeEnd = startDate < endDate ? endDate : startDate;
    const newStatus = nextStatus(statusFor(startDate));
    submitting = true; setSaveState(`Applying ${readableDate(rangeStart)} – ${readableDate(rangeEnd)}…`);
    try {
      const data = await request(app.dataset.availabilityRangeUrl, {
        name,
        start_date: rangeStart,
        end_date: rangeEnd,
        status: newStatus,
      });
      nameInput.value = data.participant.name;
      localStorage.setItem(storageKey, data.participant.name);
      results = data.results;
      renderCalendar(); renderResults(); setSaveState('Saved range');
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
  document.addEventListener('pointermove', handleRangePointerMove, { passive: false });
  document.addEventListener('pointerup', (event) => finishRangeGesture(event));
  document.addEventListener('pointercancel', (event) => finishRangeGesture(event, true));
  proposalForm.addEventListener('submit', submitProposal);
  proposalCancel.addEventListener('click', resetProposalForm);
  proposalType.addEventListener('change', updateStayDetails);
  updateStayDetails();
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
