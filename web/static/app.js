const form = document.querySelector('#query-form');
const questionInput = document.querySelector('#question');
const submitButton = document.querySelector('#submit');
const hero = document.querySelector('#hero');
const conversation = document.querySelector('#conversation');
const userMessage = document.querySelector('#user-message');
const agentFlow = document.querySelector('#agent-flow');
const answerCard = document.querySelector('#answer-card');
const answerContent = document.querySelector('#answer-content');
const answerKicker = document.querySelector('#answer-kicker');
const answerTitle = document.querySelector('#answer-title');
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

const steps = new Map();
const agentCards = new Map();

const AGENTS = {
  classifier: {
    order: 'AGENT 01',
    name: 'Request Classifier',
    role: 'Decides if the solution needs a raw-data check',
    image: '/static/images/classifier-agent.png'
  },
  solver: {
    order: 'AGENT 02',
    name: 'Crew Ops Solver',
    role: 'Builds the answer using the complete MCP toolkit',
    image: '/static/images/solver-agent.png'
  },
  reengineering: {
    order: 'AGENT 03',
    name: 'Re-engineering Checker',
    role: 'Checks key solution inputs using basic read tools',
    image: '/static/images/reengineering-agent.png'
  },
  legal: {
    order: 'AGENT 04',
    name: 'Legal Compliance Agent',
    role: 'Checks the proposed action against every rule in rules.json',
    image: '/static/images/legal-agent.png'
  }
};

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

function ensureAgentCard(agentName) {
  if (agentCards.has(agentName)) return agentCards.get(agentName);
  const normalizedName = String(agentName || 'solver').toLowerCase();
  const agent = AGENTS[normalizedName] || {
    order: 'AGENT',
    name: normalizedName.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase()),
    role: 'Processes this stage of the request',
    image: AGENTS.solver.image
  };
  const card = document.createElement('article');
  card.className = 'agent-card active';
  card.dataset.agent = normalizedName;
  card.innerHTML = `
    <header class="agent-card-header">
      <div class="agent-avatar"><img src="${agent.image}" alt="${escapeHtml(agent.name)} avatar"></div>
      <div class="agent-identity">
        <span>${agent.order}</span>
        <h2>${escapeHtml(agent.name)}</h2>
        <p>${escapeHtml(agent.role)}</p>
      </div>
      <div class="agent-state"><i></i><span>Working</span></div>
    </header>
    <section class="agent-tools" hidden>
      <h3>Tool calls</h3>
      <div class="agent-tool-list"></div>
    </section>
    <section class="agent-output" hidden>
      <div class="agent-output-label">Agent output</div>
      <div class="agent-output-content"></div>
    </section>`;
  agentFlow.appendChild(card);
  agentCards.set(agentName, card);
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  return card;
}

function setAgentState(agentName, state, label) {
  const card = ensureAgentCard(agentName);
  card.classList.remove('active', 'complete', 'skipped', 'failed');
  card.classList.add(state);
  card.querySelector('.agent-state span').textContent = label;
}

function setAgentOutput(agentName, content, plain = false) {
  const card = ensureAgentCard(agentName);
  const output = card.querySelector('.agent-output');
  output.hidden = false;
  const target = output.querySelector('.agent-output-content');
  target.innerHTML = plain ? `<strong>${escapeHtml(content)}</strong>` : renderMarkdown(content);
  output.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function showNoToolsIfEmpty(agentName, message = 'No MCP tools were called.') {
  const card = ensureAgentCard(agentName);
  const toolList = card.querySelector('.agent-tool-list');
  if (toolList.children.length) return;
  card.querySelector('.agent-tools').hidden = false;
  toolList.innerHTML = `<div class="no-tools">${escapeHtml(message)}</div>`;
}

function addToolStep(event) {
  const agentName = event.agent || 'solver';
  const card = ensureAgentCard(agentName);
  const toolSection = card.querySelector('.agent-tools');
  toolSection.hidden = false;
  const toolList = card.querySelector('.agent-tool-list');
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
  toolList.appendChild(node);
  steps.set(event.id, node);
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
}

function resetUI(question) {
  steps.clear();
  agentCards.clear();
  agentFlow.replaceChildren();
  userMessage.textContent = question;
  answerContent.replaceChildren();
  answerKicker.textContent = 'CREW OPS ADVISOR';
  answerTitle.textContent = 'Answer';
  answerCard.hidden = true;
  errorCard.hidden = true;
  newQuery.hidden = true;
  hero.hidden = true;
  conversation.hidden = false;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function finishUI() {
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
        if (event.type === 'classification_started') {
          ensureAgentCard('classifier');
          showNoToolsIfEmpty('classifier', 'No MCP tools — classification only.');
        } else if (event.type === 'classification_completed') {
          setAgentOutput('classifier', event.needs_check ? 'YES — re-engineering check required' : 'NO — direct answer only', true);
          setAgentState('classifier', 'complete', 'Complete');
        } else if (event.type === 'thinking') {
          ensureAgentCard(event.agent || 'solver');
        } else if (event.type === 'tool_started') {
          addToolStep(event);
        } else if (event.type === 'tool_completed') {
          completeToolStep(event);
        } else if (event.type === 'solver_completed') {
          showNoToolsIfEmpty('solver');
          setAgentOutput('solver', event.content);
          setAgentState('solver', 'complete', 'Complete');
        } else if (event.type === 'reengineering_started') {
          ensureAgentCard('reengineering');
        } else if (event.type === 'reengineering_completed') {
          showNoToolsIfEmpty('reengineering');
          setAgentOutput('reengineering', event.content);
          setAgentState('reengineering', 'complete', 'Complete');
        } else if (event.type === 'legal_started') {
          ensureAgentCard('legal');
        } else if (event.type === 'legal_completed') {
          showNoToolsIfEmpty('legal');
          setAgentOutput('legal', event.content);
          setAgentState('legal', 'complete', 'Complete');
        } else if (event.type === 'answer') {
          answerKicker.textContent = event.legal_checked ? 'LEGAL COMPLIANCE COMPLETE' : 'CREW OPS ADVISOR';
          answerTitle.textContent = 'Final answer';
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
    for (const [name, card] of agentCards) {
      if (card.classList.contains('active')) setAgentState(name, 'failed', 'Stopped');
    }
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
