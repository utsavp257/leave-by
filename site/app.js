/* Leave-by.
 *
 * The map is not a control that happens to be shaped like a city. It is the
 * chart: every zone is shaded by the answer for that zone, so the shape of the
 * problem is visible before anything is clicked. Selecting a zone only asks the
 * map to explain one of the shapes it is already showing.
 *
 * Bars keep the grammar the map sets up. Solid to the median journey, hatched
 * from there to the ninetieth percentile. The hatching is the part you cannot
 * plan around, and on most trips it is nearly as long as the trip.
 *
 * No framework, no build. The motion patterns here are the familiar ones -
 * staggered entrance, reveal on scroll, counting numbers, spring easing - written
 * directly against the platform because the page has no bundler to feed.
 */

const BLOCK_LABELS = {
  early: "Before 7am",
  am: "7–10am",
  midday: "10am–4pm",
  pm: "4–7pm",
  evening: "After 7pm",
};

const SHADE_MODES = {
  leave: { label: "Leave-by", low: "quicker", high: "longer" },
  buffer: { label: "Unpredictability", low: "steady", high: "wild" },
};

const RAMP = ["--s1", "--s2", "--s3", "--s4", "--s5"];

const state = {
  data: null,
  map: null,
  airport: "JFK",
  block: "pm",
  shade: "leave",
  origin: null,
  pin: null,
};

const el = (id) => document.getElementById(id);
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ── boot ─────────────────────────────────────────────────── */

async function boot() {
  const [data, map] = await Promise.all([
    fetch("data/leaveby.json").then((r) => r.json()),
    fetch("data/map.json").then((r) => r.json()),
  ]);
  state.data = data;
  state.map = map;

  buildSegmented("airport", airportsAvailable(), (a) => a, "airport");
  buildSegmented("block", data.blocks, (b) => BLOCK_LABELS[b] || b, "block");
  buildSegmented("shade", Object.keys(SHADE_MODES), (s) => SHADE_MODES[s].label, "shade");

  drawMap();
  pickDefault();
  paintMap();
  renderAnswer();
  wireSearch();
  revealOnScroll();
}

function airportsAvailable() {
  return Object.keys(state.data.airports).filter(
    (a) => Object.keys(state.data.airports[a]).length > 0
  );
}

function buildSegmented(id, values, label, key) {
  const host = el(id);
  host.innerHTML = "";
  for (const value of values) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label(value);
    button.setAttribute("aria-pressed", String(state[key] === value));
    button.addEventListener("click", () => {
      if (state[key] === value) return;
      state[key] = value;
      [...host.children].forEach((b) =>
        b.setAttribute("aria-pressed", String(b === button))
      );
      if (key === "airport") {
        pickDefault();
        fillSearchOptions();
      }
      paintMap();
      renderAnswer();
    });
    host.appendChild(button);
  }
}

/* ── the map ──────────────────────────────────────────────── */

const AIRPORT_ZONES = { JFK: "132", LGA: "138", EWR: "1" };

function drawMap() {
  const svg = el("map");
  svg.setAttribute("viewBox", state.map.viewbox.join(" "));
  const frag = document.createDocumentFragment();

  for (const [id, shape] of Object.entries(state.map.zones)) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", shape.d);
    path.setAttribute("class", "zone");
    path.dataset.zone = id;
    path.dataset.name = shape.name;
    frag.appendChild(path);
  }
  svg.appendChild(frag);

  state.pin = document.createElementNS("http://www.w3.org/2000/svg", "g");
  state.pin.setAttribute("class", "pin");
  state.pin.innerHTML =
    '<circle class="pin-halo" r="16"></circle>' +
    '<circle class="pin-ring" r="7"></circle>' +
    '<circle class="pin-core" r="2.6"></circle>';
  svg.appendChild(state.pin);

  svg.addEventListener("pointermove", onHover);
  svg.addEventListener("pointerleave", hideTip);
  svg.addEventListener("click", (event) => {
    const direct = event.target.closest(".zone-live");
    const id = direct ? direct.dataset.zone : nearestZone(event);
    if (!id) return;
    select(id);
  });
}

/* Midtown is about four pixels wide on a phone, so requiring a direct hit makes
 * the map decorative. A tap that lands near a zone picks that zone; a tap out in
 * the harbour still does nothing. */
function nearestZone(event) {
  const svg = el("map");
  const rect = svg.getBoundingClientRect();
  const [vx, vy, vw, vh] = state.map.viewbox;
  const x = vx + ((event.clientX - rect.left) / rect.width) * vw;
  const y = vy + ((event.clientY - rect.top) / rect.height) * vh;

  const zones = zonesForAirport();
  let best = null;
  let bestDistance = Infinity;
  for (const [id, shape] of Object.entries(state.map.zones)) {
    if (!shape.c || !zones[id] || valueFor(zones[id]) == null) continue;
    const d = Math.hypot(shape.c[0] - x, shape.c[1] - y);
    if (d < bestDistance) {
      bestDistance = d;
      best = id;
    }
  }
  // The forgiveness radius is defined in screen pixels and converted, so it is
  // the same physical distance on a phone as on a monitor. A fixed value in map
  // units would be generous on a wide screen and useless on a narrow one.
  const unitsPerPixel = vw / rect.width;
  return bestDistance <= 22 * unitsPerPixel ? best : null;
}

function select(id) {
  state.origin = id;
  const shape = state.map.zones[id];
  if (shape) el("search").value = shape.name;
  paintMap();
  renderAnswer();
}

function zonesForAirport() {
  return state.data.airports[state.airport] || {};
}

function valueFor(zone) {
  const cell = zone && zone.blocks[state.block];
  if (!cell || !cell.car) return null;
  return state.shade === "buffer" ? cell.car.p90 - cell.car.p50 : cell.car.p90;
}

function paintMap() {
  const zones = zonesForAirport();
  const values = [];
  for (const zone of Object.values(zones)) {
    const v = valueFor(zone);
    if (v != null) values.push(v);
  }
  if (!values.length) return;

  // Quantile breaks rather than equal steps. Travel times bunch heavily around
  // the middle, and even slicing would leave four of five colours unused.
  values.sort((a, b) => a - b);
  const breaks = [0.2, 0.4, 0.6, 0.8].map(
    (q) => values[Math.floor(q * (values.length - 1))]
  );

  const styles = getComputedStyle(document.documentElement);
  const ramp = RAMP.map((name) => styles.getPropertyValue(name).trim());
  const airportZone = AIRPORT_ZONES[state.airport];

  for (const path of el("map").querySelectorAll(".zone")) {
    const id = path.dataset.zone;
    path.classList.remove("zone-live", "zone-dead", "zone-airport", "zone-selected");

    if (id === airportZone) {
      path.classList.add("zone-airport");
      path.style.fill = "";
      continue;
    }
    const value = valueFor(zones[id]);
    if (value == null) {
      path.classList.add("zone-dead");
      path.style.fill = "";
      continue;
    }
    let step = 0;
    while (step < breaks.length && value > breaks[step]) step++;
    path.style.fill = ramp[step];
    path.classList.add("zone-live");
    if (id === state.origin) path.classList.add("zone-selected");
  }

  const shape = state.map.zones[state.origin];
  if (shape && shape.c) {
    state.pin.setAttribute("transform", `translate(${shape.c[0]} ${shape.c[1]})`);
    state.pin.classList.add("on");
  } else {
    state.pin.classList.remove("on");
  }

  const mode = SHADE_MODES[state.shade];
  el("legend-low").textContent = `${mode.low} · ${values[0]} min`;
  el("legend-high").textContent = `${values[values.length - 1]} min · ${mode.high}`;
}

function onHover(event) {
  const path = event.target.closest(".zone-live, .zone-airport");
  const tip = el("tip");
  if (!path) return hideTip();

  const zone = zonesForAirport()[path.dataset.zone];
  const value = valueFor(zone);
  const shell = el("map").getBoundingClientRect();
  const box = path.getBoundingClientRect();

  tip.innerHTML = value == null
    ? `<b>${path.dataset.name}</b>`
    : `<b>${zone.zone}</b><span>${value} min ${state.shade === "buffer" ? "of slack" : "before your flight"}</span>`;
  tip.style.left = `${box.left + box.width / 2 - shell.left}px`;
  tip.style.top = `${box.top - shell.top}px`;
  tip.classList.add("on");
}

function hideTip() {
  el("tip").classList.remove("on");
}

/* ── choosing a default ───────────────────────────────────── */

function pickDefault() {
  const zones = zonesForAirport();
  if (state.origin && zones[state.origin]) return;

  // Open on the widest honest disagreement between the two modes: a page that
  // lands on a tie looks like it has nothing to say.
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
  state.origin = best || Object.keys(zones)[0] || null;
  const zone = zones[state.origin];
  if (zone) el("search").value = zone.zone;
}

function wireSearch() {
  fillSearchOptions();
  const input = el("search");
  input.addEventListener("change", () => {
    const zones = zonesForAirport();
    const match = Object.entries(zones).find(
      ([, z]) => z.zone.toLowerCase() === input.value.trim().toLowerCase()
    );
    if (!match) return;
    state.origin = match[0];
    paintMap();
    renderAnswer();
  });
}

function fillSearchOptions() {
  const list = el("zone-list");
  list.innerHTML = "";
  const zones = zonesForAirport();
  const names = Object.values(zones)
    .map((z) => z.zone)
    .sort((a, b) => a.localeCompare(b));
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    list.appendChild(option);
  }
}

/* ── the answer ───────────────────────────────────────────── */

function renderAnswer() {
  const host = el("answer");
  const zone = zonesForAirport()[state.origin];
  host.innerHTML = "";

  if (!zone) {
    host.innerHTML = `<p class="verdict">Pick a neighbourhood on the map to see when to leave.</p>`;
    return;
  }

  const cell = zone.blocks[state.block];
  const place = document.createElement("div");
  place.className = "answer-place";
  place.textContent = `${zone.zone} · ${zone.borough} → ${state.airport}`;
  host.appendChild(place);

  if (!cell) {
    const none = document.createElement("p");
    none.className = "verdict";
    none.textContent = `Too few recorded trips from ${zone.zone} at this time of day to say anything honest.`;
    host.appendChild(none);
    return;
  }

  const { car, transit } = cell;
  const leaveBy = cell.leave_by;

  const headline = document.createElement("div");
  headline.className = "leave-by";
  const value = document.createElement("span");
  value.className = "leave-by-value";
  value.textContent = "0";
  const unit = document.createElement("span");
  unit.className = "leave-by-unit";
  unit.textContent = `minutes ahead, leaving ${(BLOCK_LABELS[state.block] || "").toLowerCase()}`;
  headline.append(value, unit);
  host.appendChild(headline);
  countTo(value, leaveBy);

  const verdict = document.createElement("p");
  verdict.className = "verdict";
  verdict.innerHTML = verdictLine(zone, cell);
  host.appendChild(verdict);

  const longest = Math.max(car ? car.p90 : 0, transit ? transit.p90 : 0, 30);
  const scale = Math.ceil(longest / 30) * 30;

  const bars = document.createElement("div");
  bars.className = "bars";
  bars.appendChild(barRow("car", "Car", "Uber, Lyft or a cab", car, scale));
  bars.appendChild(
    barRow(
      "transit",
      "Train",
      zone.via ? `${zone.via.route} from ${zone.via.station}, then the ${zone.via.link}` : "",
      transit,
      scale
    )
  );
  bars.appendChild(axisRow(scale));
  host.appendChild(bars);

  const notes = [];
  if (transit) {
    notes.push("The train figure is built conservatively, so where it wins it wins by at least this much.");
  }
  if (state.airport === "LGA" && transit) {
    notes.push(`<span class="flag">Weaker evidence</span>The bus leg is published already averaged over a month, a weekday and an hour, which hides the worst buses.`);
  }
  if (state.airport === "EWR") {
    notes.push(`<span class="flag">Car only</span>New Jersey Transit publishes punctuality percentages rather than journey times, so there is no honest train bar to draw.`);
  }
  if (notes.length) {
    const evidence = document.createElement("div");
    evidence.className = "evidence";
    evidence.innerHTML = notes.map((n) => `<p>${n}</p>`).join("");
    host.appendChild(evidence);
  }
}

function barRow(mode, label, detail, cell, scale) {
  const row = document.createElement("div");
  row.className = `bar-row bar-${mode}`;

  const head = document.createElement("div");
  head.className = "bar-head";
  head.innerHTML =
    `<div class="bar-mode"><span class="bar-dot"></span>${label} <span>${detail}</span></div>`;

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
  figure.textContent = `${cell.p50} typical · ${cell.p90} on a bad day`;
  head.appendChild(figure);
  row.appendChild(head);

  const track = document.createElement("div");
  track.className = "track";
  const solid = document.createElement("div");
  solid.className = "solid";
  const tail = document.createElement("div");
  tail.className = "tail";
  track.append(solid, tail);
  row.appendChild(track);

  // Widths are set after paint so the transition has a zero state to run from.
  requestAnimationFrame(() => {
    solid.style.width = `${(cell.p50 / scale) * 100}%`;
    tail.style.left = `${(cell.p50 / scale) * 100}%`;
    tail.style.width = `${((cell.p90 - cell.p50) / scale) * 100}%`;
  });
  return row;
}

function axisRow(scale) {
  const row = document.createElement("div");
  row.className = "axis";
  for (let minutes = 0; minutes <= scale; minutes += 30) {
    const tick = document.createElement("span");
    tick.className = "axis-tick";
    tick.style.left = `${(minutes / scale) * 100}%`;
    tick.textContent = minutes === scale ? `${minutes} min` : `${minutes}`;
    if (minutes === 0) tick.classList.add("axis-first");
    if (minutes === scale) tick.classList.add("axis-last");
    row.appendChild(tick);
  }
  return row;
}

function verdictLine(zone, cell) {
  const { car, transit, verdict } = cell;
  const where = zone.zone;

  if (!transit) {
    return `No measured train option from ${where}. The car is the only way this page can price.`;
  }
  if (!car) {
    return `Only the train is measured from ${where} at this hour.`;
  }
  if (verdict === "too close to call") {
    return `Car and train are within minutes of each other. Take whichever you prefer.`;
  }
  if (verdict === "transit") {
    return `The train beats the car on a bad day by <strong>${car.p90 - transit.p90} minutes</strong>.`;
  }
  return `The car wins even at its worst, by <strong>${transit.p90 - car.p90} minutes</strong>.`;
}

/* ── motion ───────────────────────────────────────────────── */

function countTo(node, target) {
  if (reduced) {
    node.textContent = target;
    return;
  }

  const duration = 650;
  const start = performance.now();
  let settled = false;

  const finish = () => {
    if (settled) return;
    settled = true;
    node.textContent = target;
  };

  const step = (now) => {
    // The guard below can land first if the clock and the timers ever disagree.
    // Without this check the loop would carry on and paint a half-counted
    // number back over the correct one - which is exactly what it did.
    if (settled) return;
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = Math.round(target * eased);
    if (t < 1) requestAnimationFrame(step);
    else finish();
  };

  node.textContent = "0";
  requestAnimationFrame(step);

  // Phones throttle animation frames hard when a tab is busy or backgrounded.
  // A stalled count would otherwise leave a wrong number on screen for good.
  setTimeout(finish, duration + 400);
}

function revealOnScroll() {
  const items = [...document.querySelectorAll(".rise")];
  if (reduced || !("IntersectionObserver" in window)) {
    items.forEach((n) => n.classList.add("in"));
    return;
  }

  // The masthead is above the fold and should not wait for a scroll event.
  const above = items.filter((n) => n.getBoundingClientRect().top < window.innerHeight);
  above.forEach((n, i) => setTimeout(() => n.classList.add("in"), 80 * i));

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("in");
        if (entry.target.id === "then-now") animateThenNow(entry.target);
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -12% 0px" }
  );
  items.filter((n) => !above.includes(n)).forEach((n) => observer.observe(n));

  const thenNow = el("then-now");
  if (above.includes(thenNow)) animateThenNow(thenNow);
}

function animateThenNow(root) {
  root.querySelectorAll(".tn-fill").forEach((fill, i) => {
    setTimeout(() => {
      fill.style.width = `${fill.dataset.width}%`;
    }, reduced ? 0 : 120 * i);
  });
  root.querySelectorAll("[data-count]").forEach((node, i) => {
    setTimeout(() => countTo(node, Number(node.dataset.count)), reduced ? 0 : 120 * i);
  });
}

boot();
