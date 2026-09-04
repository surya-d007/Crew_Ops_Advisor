const form = document.querySelector('#query-form');
const questionInput = document.querySelector('#question');
const submitButton = document.querySelector('#submit');
const hero = document.querySelector('#hero');
const conversation = document.querySelector('#conversation');
const userMessage = document.querySelector('#user-message');
const timeline = document.querySelector('#timeline');
const workCard = document.querySelector('#work-card');
const liveStatus = document.querySelector('#live-status');
const elapsed = document.querySelector('#elapsed');
const answerCard = document.querySelector('#answer-card');
const answerContent = document.querySelector('#answer-content');
const errorCard = document.querySelector('#error-card');
const errorContent = document.querySelector('#error-content');
const newQuery = document.querySelector('#new-query');

const TOOL_COPY = {
  get_crew: ['Checking crew profile', 'Looking up role, base, status, and aircraft ratings.'],
  search_crew: ['Searching crew records', 'Finding crew who match the required role, base, status, or rating.'],
  get_flight: ['Checking flight details', 'Looking up the selected flight leg and its schedule.'],
  search_flights: ['Searching the flight schedule', 'Finding flight legs that match the route, date, or flight number.'],
  count_flights: ['Counting matching flights', 'Calculating the exact number of scheduled flight legs.'],
  search_station_window: ['Checking the disruption window', 'Finding arrivals and departures inside the station closure period.'],
  get_pairing: ['Reviewing the pairing', 'Loading its flights, crew, report times, and release times.'],
  get_crew_roster: ['Reviewing crew roster', 'Checking the crew member’s planned duties and pairings.'],
  get_flagged_roster_exceptions: ['Checking roster exceptions', 'Looking for known compliance problems in the roster.'],
  get_reserves: ['Searching reserve crew', 'Finding reserves whose date, base, and rank match the request.'],
  assess_reserves_for_aircraft_duty: ['Assessing reserve eligibility', 'Checking report window, base, rank, rating, status, and certifications.'],
  get_duty_clock: ['Checking duty limits', 'Reviewing rest and rolling duty and flight-hour totals.'],
  search_crew_by_rolling_duty: ['Calculating rolling duty hours', 'Finding crew at or above the requested duty-hour threshold.'],
  get_certifications: ['Checking certifications', 'Reviewing licence, medical, and training validity.'],
  search_certifications: ['Searching certification dates', 'Finding certifications in the requested expiry window.'],
  get_risk_signal: ['Checking disruption risk', 'Loading the crew member’s supplied risk score and its drivers.'],
  get_rules: ['Reviewing operating rules', 'Loading the rules needed to evaluate legality.'],
  get_costs: ['Checking recovery costs', 'Loading the applicable callout, delay, positioning, and cancellation costs.'],
  list_scenarios: ['Reviewing scenarios', 'Finding relevant public operational scenarios.'],
  get_scenario: ['Loading scenario details', 'Reviewing the selected operational scenario.'],
  get_question: ['Loading evaluation question', 'Reviewing the selected public evaluation prompt.']
};

let timer;
let startedAt;
const steps = new Map();

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function renderMarkdown(markdown) {
  const lines = String(markdown).split('\n');
  const html = [];
  let listType = null;
  let inTable = false;

  const closeList = () => {
    if (listType) html.push(`</${listType}>`);
    listType = null;
  };
  const closeTable = () => {
    if (inTable) html.push('</tbody></table>');
    inTable = false;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    const next = (lines[index + 1] || '').trim();

    if (line.includes('|') && /^\|?\s*:?-+/.test(next)) {
      closeList();
      const cells = line.replace(/^\||\|$/g, '').split('|');
      html.push('<table><thead><tr>' + cells.map(c => `<th>${inlineMarkdown(c.trim())}</th>`).join('') + '</tr></thead><tbody>');
      inTable = true;
      index += 1;
      continue;
    }
    if (inTable && line.includes('|')) {
      const cells = line.replace(/^\||\|$/g, '').split('|');
      html.push('<tr>' + cells.map(c => `<td>${inlineMarkdown(c.trim())}</td>`).join('') + '</tr>');
      continue;
    }
    closeTable();

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length + 1;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    const numbered = line.match(/^\d+\.\s+(.+)$/);
    if (bullet || numbered) {
      const wanted = bullet ? 'ul' : 'ol';
      if (listType !== wanted) {
        closeList();
        html.push(`<${wanted}>`);
        listType = wanted;
      }
      html.push(`<li>${inlineMarkdown((bullet || numbered)[1])}</li>`);
      continue;
    }
    closeList();
    if (line) html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  closeTable();
  return html.join('');
}

function compactArgs(args) {
  const entries = Object.entries(args || {}).filter(([, value]) => value !== '' && value !== null && value !== undefined);
  if (!entries.length) return '';
  return entries.slice(0, 4).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`).join(' · ');
}

function addToolStep(event) {
  const copy = TOOL_COPY[event.name] || [`Running ${event.name.replaceAll('_', ' ')}`, 'Retrieving the information needed to answer your question.'];
  const args = compactArgs(event.arguments);
  const node = document.createElement('div');
  node.className = 'tool-step running';
  node.dataset.id = event.id;
  node.innerHTML = `
    <span class="step-icon">•</span>
    <div class="step-copy">
      <div class="step-title"><span>${escapeHtml(copy[0])}</span><code>${escapeHtml(event.name)}</code></div>
      <div class="step-description">${escapeHtml(args || copy[1])}</div>
    </div>`;
  timeline.appendChild(node);
  steps.set(event.id, node);
  liveStatus.textContent = copy[1];
  node.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function completeToolStep(event) {
  const node = steps.get(event.id);
  if (!node) return;
  node.classList.remove('running');
  node.classList.add(event.succeeded ? 'complete' : 'failed');
  node.querySelector('.step-icon').textContent = event.succeeded ? '✓' : '!';
  const detail = document.createElement('details');
  detail.className = 'tool-detail';
  detail.innerHTML = `<summary>View tool result</summary><pre>${escapeHtml(JSON.stringify(event.result, null, 2))}</pre>`;
  node.querySelector('.step-copy').appendChild(detail);
  liveStatus.textContent = event.succeeded ? 'Tool completed—reviewing the returned evidence…' : 'A tool failed—checking whether I can continue…';
}

function resetUI(question) {
  clearInterval(timer);
  steps.clear();
  timeline.replaceChildren();
  userMessage.textContent = question;
  answerContent.replaceChildren();
  answerCard.hidden = true;
  errorCard.hidden = true;
  newQuery.hidden = true;
  workCard.hidden = false;
  liveStatus.textContent = 'Understanding what you’re looking for…';
  elapsed.textContent = '0s';
  hero.hidden = true;
  conversation.hidden = false;
  startedAt = Date.now();
  timer = setInterval(() => {
    elapsed.textContent = `${Math.floor((Date.now() - startedAt) / 1000)}s`;
  }, 1000);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function finishUI() {
  clearInterval(timer);
  submitButton.disabled = false;
  newQuery.hidden = false;
}

async function runQuery(question) {
  resetUI(question);
  submitButton.disabled = true;

  try {
    const response = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question })
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error || `Request failed (${response.status})`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === 'thinking') {
          liveStatus.textContent = event.round === 1 ? 'Understanding your request and choosing the right data tools…' : 'Connecting the evidence and deciding what to check next…';
        } else if (event.type === 'tool_started') {
          addToolStep(event);
        } else if (event.type === 'tool_completed') {
          completeToolStep(event);
        } else if (event.type === 'answer') {
          liveStatus.textContent = 'Analysis complete';
          answerContent.innerHTML = renderMarkdown(event.content);
          answerCard.hidden = false;
          answerCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else if (event.type === 'error') {
          throw new Error(event.message);
        } else if (event.type === 'done') {
          finishUI();
        }
      }
      if (done) break;
    }
  } catch (error) {
    errorContent.textContent = error.message || 'Unknown error';
    errorCard.hidden = false;
    liveStatus.textContent = 'Stopped before completing the answer';
    finishUI();
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (question) runQuery(question);
});

questionInput.addEventListener('input', () => {
  questionInput.style.height = 'auto';
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 160)}px`;
});

questionInput.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll('.suggestions button').forEach(button => {
  button.addEventListener('click', () => {
    questionInput.value = button.textContent;
    form.requestSubmit();
  });
});

newQuery.addEventListener('click', () => {
  conversation.hidden = true;
  hero.hidden = false;
  questionInput.value = '';
  questionInput.style.height = 'auto';
  questionInput.focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});
