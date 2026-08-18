/* Leave-by times, drawn as bars.
 *
 * The bar is the whole argument, so it is worth saying what it encodes. Solid
 * runs to the median journey. Hatching runs from there to the ninetieth
 * percentile, and that hatched part is the buffer - the time you spend leaving
 * early because the road might betray you. On most trips it is nearly as long
 * as the journey itself, which is the finding.
 *
 * Both modes share one scale so the comparison is honest at a glance.
 */

const BLOCK_LABELS = {
  early: "Before 7am",
  am: "7–10am",
  midday: "10am–4pm",
  pm: "4–7pm",
  evening: "After 7pm",
};

const state = { data: null, airport: "JFK", origin: null, block: "pm" };

const el = (id) => document.getElementById(id);

async function boot() {
  const response = await fetch("data/leaveby.json");
  state.data = await response.json();

  buildAirports();
  buildBlocks();
  buildOrigins();
  render();
}

function airportsAvailable() {
  return Object.keys(state.data.airports).filter(
    (a) => Object.keys(state.data.airports[a]).length > 0
  );
}

function buildAirports() {
  const host = el("airport");
  host.innerHTML = "";
  for (const airport of airportsAvailable()) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = airport;
    button.setAttribute("aria-pressed", String(airport === state.airport));
    button.addEventListener("click", () => {
      state.airport = airport;
      buildAirports();
      buildOrigins();
      render();
    });
    host.appendChild(button);
  }
}

function buildBlocks() {
  const host = el("block");
  host.innerHTML = "";
  for (const block of state.data.blocks) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = BLOCK_LABELS[block] || block;
    button.setAttribute("aria-pressed", String(block === state.block));
    button.addEventListener("click", () => {
      state.block = block;
      buildBlocks();
      render();
    });
    host.appendChild(button);
  }
}

function buildOrigins() {
  const zones = state.data.airports[state.airport];
  const select = el("origin");
  const previous = state.origin;
  select.innerHTML = "";

  const byBorough = new Map();
  for (const [id, zone] of Object.entries(zones)) {
    if (!byBorough.has(zone.borough)) byBorough.set(zone.borough, []);
    byBorough.get(zone.borough).push([id, zone]);
  }

  // Places with a train option first, since that is the comparison the page is
  // actually about; everything else still available underneath.
  for (const borough of [...byBorough.keys()].sort()) {
    const group = document.createElement("optgroup");
    group.label = borough;
    const entries = byBorough.get(borough).sort((a, b) => {
      const viaDiff = Number(Boolean(b[1].via)) - Number(Boolean(a[1].via));
      return viaDiff || a[1].zone.localeCompare(b[1].zone);
    });
    for (const [id, zone] of entries) {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = zone.via ? zone.zone : `${zone.zone} — car only`;
      group.appendChild(option);
    }
    select.appendChild(group);
  }

  if (previous && zones[previous]) {
    select.value = previous;
  } else {
    select.value = mostInstructive(zones);
  }
  state.origin = select.value;
  select.onchange = () => {
    state.origin = select.value;
    render();
  };
}

/* Open on a place where the two modes actually disagree.
 *
 * Landing on a zone where the car and the train are within a few minutes makes
 * the page look like it has nothing to say. The widest honest gap is the
 * clearest demonstration of what the bars are for, and the reader can pick
 * their own street immediately afterwards.
 */
function mostInstructive(zones) {
  let best = null;
  let bestGap = -Infinity;
  for (const [id, zone] of Object.entries(zones)) {
    const cell = zone.blocks[state.block];
    if (!cell || !cell.car || !cell.transit) continue;
    const gap = cell.car.p90 - cell.transit.p90;
    if (gap > bestGap) {
      bestGap = gap;
      best = id;
    }
  }
  if (best) return best;
  const withTrain = Object.entries(zones).find(([, z]) => z.via);
  return withTrain ? withTrain[0] : Object.keys(zones)[0];
}

function barRow(mode, label, detail, cell, scale) {
  const row = document.createElement("div");
  row.className = `bar-row bar-${mode}`;

  const head = document.createElement("div");
  head.className = "bar-head";
  const name = document.createElement("div");
  name.className = "bar-mode";
  name.innerHTML = `${label} <span>${detail}</span>`;
  head.appendChild(name);

  if (!cell) {
    row.appendChild(head);
    const empty = document.createElement("div");
    empty.className = "bar-empty";
    empty.textContent = "No measured option from here";
    row.appendChild(empty);
    return row;
  }

  const figure = document.createElement("div");
  figure.className = "bar-figure";
  figure.textContent = `${cell.p50} min typical · ${cell.p90} min on a bad day`;
  head.appendChild(figure);
  row.appendChild(head);

  const track = document.createElement("div");
  track.className = "track";

  const solid = document.createElement("div");
  solid.className = "solid";
  solid.style.width = `${(cell.p50 / scale) * 100}%`;

  const tail = document.createElement("div");
  tail.className = "tail";
  tail.style.left = `${(cell.p50 / scale) * 100}%`;
  tail.style.width = `${((cell.p90 - cell.p50) / scale) * 100}%`;

  // Anchored from the right so the label grows leftwards from the tail's end.
  // Positioning it from the left and pulling it back with a transform leaves a
  // layout box hanging off the right edge, which widens the whole page on a
  // phone even though the text looks fine.
  const tick = document.createElement("div");
  tick.className = "tick";
  tick.style.right = `${100 - (cell.p90 / scale) * 100}%`;
  tick.textContent = `leave ${cell.p90} min ahead`;

  track.append(solid, tail, tick);
  row.appendChild(track);
  return row;
}

function render() {
  const zone = state.data.airports[state.airport][state.origin];
  const bars = el("bars");
  const evidence = el("evidence");
  bars.innerHTML = "";
  evidence.innerHTML = "";

  if (!zone) return;
  const cell = zone.blocks[state.block];

  if (!cell) {
    el("verdict").textContent =
      `Too few recorded trips from ${zone.zone} at this time of day to say anything honest.`;
    return;
  }

  const car = cell.car;
  const transit = cell.transit;
  const scale = Math.max(car ? car.p90 : 0, transit ? transit.p90 : 0, 30) * 1.08;

  const via = zone.via;
  bars.appendChild(barRow("car", "Car", "Uber, Lyft or a cab", car, scale));
  bars.appendChild(
    barRow(
      "transit",
      "Train",
      via ? `${via.route} from ${via.station}, then the ${via.link}` : "",
      transit,
      scale
    )
  );

  el("verdict").innerHTML = verdictLine(zone, cell);

  const notes = [];
  if (transit) {
    notes.push(
      "The train figure is built conservatively, so where it wins it wins by at least this much."
    );
  }
  if (state.airport === "LGA" && transit) {
    notes.push(
      `<span class="flag">Weaker evidence</span> The bus leg is published already averaged over a month, a weekday and an hour, which hides the worst buses. Treat the train bar here as optimistic.`
    );
  }
  if (state.airport === "EWR") {
    notes.push(
      `<span class="flag">Car only</span> New Jersey Transit publishes punctuality percentages rather than journey times, so there is no honest train bar to draw.`
    );
  }
  evidence.innerHTML = notes.map((n) => `<p>${n}</p>`).join("");
}

function verdictLine(zone, cell) {
  const { car, transit, verdict } = cell;
  const when = (BLOCK_LABELS[state.block] || state.block).toLowerCase();
  const where = zone.zone;

  if (verdict === "car only" || !transit) {
    return `From ${where}, ${when}, leave <strong>${car.p90} minutes</strong> before you have to be at ${state.airport}.`;
  }
  if (verdict === "transit only") {
    return `From ${where}, ${when}, the train is the only measured option: leave <strong>${transit.p90} minutes</strong> ahead.`;
  }
  if (verdict === "too close to call") {
    return `From ${where}, ${when}, the two are within minutes of each other. Take whichever you prefer and leave <strong>${Math.min(car.p90, transit.p90)} minutes</strong> ahead.`;
  }
  if (verdict === "transit") {
    return `From ${where}, ${when}, the train beats the car on a bad day by <strong>${car.p90 - transit.p90} minutes</strong> — and costs about a tenth as much.`;
  }
  return `From ${where}, ${when}, the car wins even at its worst, by <strong>${transit.p90 - car.p90} minutes</strong>.`;
}

boot();
