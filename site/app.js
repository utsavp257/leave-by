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
  // Categorical, not a ramp: the answer here is a decision, not a quantity.
  verdict: { label: "Train or car", categorical: true },
};

const VERDICT_FILL = {
  transit: "var(--transit)",
  car: "var(--car)",
  "too close to call": "#5b6a7e",
};

const RAMP = ["--s1", "--s2", "--s3", "--s4", "--s5"];

/* Which part of the day it is where the reader is sitting. The page opens on
 * that rather than on a fixed rush hour, because the first question anyone has
 * is about leaving now. */
function blockNow() {
  const minutes = new Date().getHours() * 60 + new Date().getMinutes();
  const bounds = [
    ["early", 0, 420], ["am", 420, 600], ["midday", 600, 960],
    ["pm", 960, 1140], ["evening", 1140, 1440],
  ];
  const found = bounds.find(([, from, to]) => minutes >= from && minutes < to);
  return found ? found[0] : "pm";
}

const state = {
  data: null,
  map: null,
  airport: "JFK",
  block: blockNow(),
  shade: "leave",
  origin: null,
  pin: null,
  view: null,     // the live viewBox, which zooming moves
  panned: false,  // set while dragging so a pan is not read as a tap
};

const el = (id) => document.getElementById(id);
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ── boot ─────────────────────────────────────────────────── */

async function boot() {
  const [data, map, todd] = await Promise.all([
    fetch("data/leaveby.json").then((r) => r.json()),
    fetch("data/map.json").then((r) => r.json()),
    // Optional: the page still reads correctly without it.
    fetch("data/todd.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  state.data = data;
  state.map = map;
  if (todd) fillEras(todd);

  buildSegmented("airport", airportsAvailable(), (a) => a, "airport");
  buildSegmented("block", data.blocks, (b) => BLOCK_LABELS[b] || b, "block");
  buildSegmented("shade", Object.keys(SHADE_MODES), (s) => SHADE_MODES[s].label, "shade");

  drawMap();
  pickDefault();
  paintMap();
  renderAnswer();
  wireKeyboard();
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
      if (key === "airport") pickDefault();
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
  state.view = state.map.viewbox.slice();
  applyView();
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
    // A drag that ends over a zone is a pan, not a choice.
    if (state.panned) return;
    const direct = event.target.closest(".zone-live");
    const id = direct ? direct.dataset.zone : nearestZone(event);
    if (!id) return;
    select(id);
  });
  wireZoom(svg);
}

/* Midtown is about four pixels wide on a phone, so requiring a direct hit makes
 * the map decorative. A tap that lands near a zone picks that zone; a tap out in
 * the harbour still does nothing. */
function nearestZone(event) {
  const svg = el("map");
  const rect = svg.getBoundingClientRect();
  const [vx, vy, vw, vh] = state.view;
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
  if (SHADE_MODES[state.shade].categorical) return paintVerdictMap();
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

  placePin();

  const mode = SHADE_MODES[state.shade];
  el("legend-ramp").style.display = "";
  el("legend-low").textContent = `${mode.low} · ${values[0]} min`;
  el("legend-high").textContent = `${values[values.length - 1]} min · ${mode.high}`;
}

/* Shade by which way wins, rather than by how long it takes. Zones with no
 * measured train option are left dark: there is no decision to colour. */
function paintVerdictMap() {
  const zones = zonesForAirport();
  const airportZone = AIRPORT_ZONES[state.airport];
  const tally = { transit: 0, car: 0, "too close to call": 0 };

  for (const path of el("map").querySelectorAll(".zone")) {
    const id = path.dataset.zone;
    path.classList.remove("zone-live", "zone-dead", "zone-airport", "zone-selected");
    path.style.fill = "";

    if (id === airportZone) { path.classList.add("zone-airport"); continue; }

    const cell = zones[id] && zones[id].blocks[state.block];
    if (!cell || !cell.car) { path.classList.add("zone-dead"); continue; }

    path.classList.add("zone-live");
    if (id === state.origin) path.classList.add("zone-selected");
    if (!cell.transit) { path.style.fill = "var(--s1)"; continue; }
    path.style.fill = VERDICT_FILL[cell.verdict] || "var(--s1)";
    if (cell.verdict in tally) tally[cell.verdict] += 1;
  }

  placePin();
  const legend = el("legend-low");
  legend.innerHTML =
    `<span class="key"><i style="background:var(--transit)"></i>train ${tally.transit}</span>` +
    `<span class="key"><i style="background:var(--car)"></i>car ${tally.car}</span>` +
    `<span class="key"><i style="background:#5b6a7e"></i>too close ${tally["too close to call"]}</span>`;
  el("legend-high").textContent = "";
  el("legend-ramp").style.display = "none";
}

function placePin() {
  const shape = state.map.zones[state.origin];
  if (shape && shape.c) {
    state.pin.setAttribute("transform", `translate(${shape.c[0]} ${shape.c[1]})`);
    state.pin.classList.add("on");
  } else {
    state.pin.classList.remove("on");
  }
}

function onHover(event) {
  const path = event.target.closest(".zone-live, .zone-airport");
  const tip = el("tip");
  if (!path) return hideTip();

  const zone = zonesForAirport()[path.dataset.zone];
  const value = valueFor(zone);
  const shell = el("map").getBoundingClientRect();
  const box = path.getBoundingClientRect();

  const cell = zone && zone.blocks[state.block];
  let detail = "";
  if (SHADE_MODES[state.shade].categorical) {
    detail = cell && cell.transit
      ? { transit: "train wins", car: "car wins", "too close to call": "too close to call" }[cell.verdict]
      : "no measured train";
  } else if (value != null) {
    detail = `${value} min ${state.shade === "buffer" ? "of slack" : "before your flight"}`;
  }
  tip.innerHTML = zone
    ? `<b>${zone.zone}</b>${detail ? `<span>${detail}</span>` : ""}`
    : `<b>${path.dataset.name}</b>`;
  tip.style.left = `${box.left + box.width / 2 - shell.left}px`;
  tip.style.top = `${box.top - shell.top}px`;
  tip.classList.add("on");
}

function hideTip() {
  el("tip").classList.remove("on");
}

/* ── zoom and pan ─────────────────────────────────────────── */

const MAX_ZOOM = 6;

function applyView() {
  el("map").setAttribute("viewBox", state.view.join(" "));
  const base = state.map.viewbox;
  const zoomed = state.view[2] < base[2] * 0.999;
  el("map-card").classList.toggle("is-zoomed", zoomed);
}

/* Scale about a fixed point, so the place under the cursor or between the
 * fingers stays where it is. Zooming about the centre instead makes the map
 * slide away from whatever you were looking at. */
function zoomAbout(factor, clientX, clientY) {
  const base = state.map.viewbox;
  const rect = el("map").getBoundingClientRect();
  const [x, y, w, h] = state.view;

  let next = w / factor;
  next = Math.min(base[2], Math.max(base[2] / MAX_ZOOM, next));
  const scale = next / w;
  if (scale === 1) return;

  // Where the anchor sits in the current frame, as a fraction. The buttons pass
  // no coordinates, so they zoom about the middle; testing the rect instead of
  // the argument produced NaN and a viewBox the browser could not parse.
  const fx = clientX == null || !rect.width ? 0.5 : (clientX - rect.left) / rect.width;
  const fy = clientY == null || !rect.height ? 0.5 : (clientY - rect.top) / rect.height;
  const ax = x + w * fx;
  const ay = y + h * fy;

  state.view = clampView([ax - next * fx, ay - (h * scale) * fy, next, h * scale]);
  applyView();
}

/* Keep at least the middle of the city on screen. Without this a stray drag
 * leaves you looking at empty ocean with no way to tell which way is back. */
function clampView([x, y, w, h]) {
  const [bx, by, bw, bh] = state.map.viewbox;
  const slackX = Math.max(0, bw - w);
  const slackY = Math.max(0, bh - h);
  return [
    Math.min(bx + slackX, Math.max(bx - w * 0.15, x)),
    Math.min(by + slackY, Math.max(by - h * 0.15, y)),
    w,
    h,
  ];
}

function panBy(dxClient, dyClient) {
  const rect = el("map").getBoundingClientRect();
  if (!rect.width) return;
  const [x, y, w, h] = state.view;
  state.view = clampView([
    x - (dxClient / rect.width) * w,
    y - (dyClient / rect.height) * h,
    w,
    h,
  ]);
  applyView();
}

function resetView() {
  state.view = state.map.viewbox.slice();
  applyView();
}

function wireZoom(svg) {
  el("zoom-in").addEventListener("click", () => zoomAbout(1.5));
  el("zoom-out").addEventListener("click", () => zoomAbout(1 / 1.5));
  el("zoom-reset").addEventListener("click", resetView);

  // Trackpad pinch arrives as a wheel event with ctrlKey set. Plain scrolling
  // is left alone so the page still scrolls when the pointer crosses the map.
  svg.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    zoomAbout(Math.exp(-event.deltaY / 180), event.clientX, event.clientY);
  }, { passive: false });

  const points = new Map();
  let startSpread = 0;
  let startWidth = 0;
  let last = null;

  svg.addEventListener("pointerdown", (event) => {
    svg.setPointerCapture(event.pointerId);
    points.set(event.pointerId, event);
    state.panned = false;
    if (points.size === 2) {
      const [a, b] = [...points.values()];
      startSpread = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      startWidth = state.view[2];
    } else {
      last = { x: event.clientX, y: event.clientY, moved: 0 };
    }
  });

  svg.addEventListener("pointermove", (event) => {
    if (!points.has(event.pointerId)) return;
    points.set(event.pointerId, event);

    if (points.size === 2) {
      const [a, b] = [...points.values()];
      const spread = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (startSpread > 0) {
        state.panned = true;
        const target = startWidth / (spread / startSpread);
        zoomAbout(state.view[2] / target, (a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
      }
      return;
    }

    if (!last) return;
    const dx = event.clientX - last.x;
    const dy = event.clientY - last.y;
    last.moved += Math.abs(dx) + Math.abs(dy);
    // Six pixels of slop, so a tap with a shaky hand still selects.
    if (last.moved > 6) {
      state.panned = true;
      hideTip();
      panBy(dx, dy);
    }
    last.x = event.clientX;
    last.y = event.clientY;
  });

  const release = (event) => {
    points.delete(event.pointerId);
    if (points.size < 2) startSpread = 0;
    if (points.size === 0) last = null;
  };
  svg.addEventListener("pointerup", release);
  svg.addEventListener("pointercancel", release);
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
}

/* Arrow keys move to the nearest neighbourhood in that direction.
 *
 * The text box that used to select a zone is gone, for a quieter page. A map you
 * can only click is a map some people cannot use at all, so the map itself takes
 * focus and the arrows walk it: the closest zone whose centre lies in the
 * direction pressed, preferring ones nearly straight ahead over ones off to the
 * side.
 */
function wireKeyboard() {
  const steps = {
    ArrowLeft: [-1, 0], ArrowRight: [1, 0],
    ArrowUp: [0, -1], ArrowDown: [0, 1],
  };
  el("map").addEventListener("keydown", (event) => {
    const step = steps[event.key];
    if (!step) return;
    event.preventDefault();
    const next = neighbourTowards(step);
    if (next) select(next);
  });
}

function neighbourTowards([dx, dy]) {
  const here = state.map.zones[state.origin];
  if (!here || !here.c) return null;
  const zones = zonesForAirport();

  let best = null;
  let bestCost = Infinity;
  for (const [id, shape] of Object.entries(state.map.zones)) {
    if (id === state.origin || !shape.c) continue;
    if (!zones[id] || valueFor(zones[id]) == null) continue;

    const ox = shape.c[0] - here.c[0];
    const oy = shape.c[1] - here.c[1];
    const along = ox * dx + oy * dy;
    if (along <= 0) continue;
    const across = Math.abs(ox * dy - oy * dx);
    // Sideways drift costs triple, so "left" does not wander diagonally.
    const cost = along + across * 3;
    if (cost < bestCost) {
      bestCost = cost;
      best = id;
    }
  }
  return best;
}

/* ── the answer ───────────────────────────────────────────── */

function renderAnswer() {
  const lead = el("answer-lead");
  const detail = el("answer-detail");
  const zone = zonesForAirport()[state.origin];
  lead.innerHTML = "";
  detail.innerHTML = "";
  detail.hidden = false;

  if (!zone) {
    lead.innerHTML = `<p class="verdict">Pick a neighbourhood on the map to see when to leave.</p>`;
    detail.hidden = true;
    return;
  }

  const cell = zone.blocks[state.block];
  const place = document.createElement("div");
  place.className = "answer-place";
  place.textContent = `${zone.zone} · ${zone.borough} → ${state.airport}`;
  lead.appendChild(place);

  if (!cell) {
    const none = document.createElement("p");
    none.className = "verdict";
    none.textContent = `Too few recorded trips from ${zone.zone} at this time of day to say anything honest.`;
    lead.appendChild(none);
    detail.hidden = true;
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
  lead.appendChild(headline);
  countTo(value, leaveBy);

  const verdict = document.createElement("p");
  verdict.className = "verdict";
  verdict.innerHTML = verdictLine(zone, cell);
  lead.appendChild(verdict);

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
  detail.appendChild(bars);

  const notes = [];
  if (car && car.fare != null) {
    notes.push(
      "Car fares are a median across every service tier — these records cannot " +
      "separate UberX from XL or Black — so the figure lands between them. " +
      "Checked live from Herald Square at 5pm: UberX $110, XL $150, against a " +
      "measured $124 there. Tips excluded."
    );
  }
  if (transit) {
    notes.push("The train figure is built conservatively, so where it wins it wins by at least this much.");
  }
  if (state.airport === "LGA" && transit) {
    notes.push(`<span class="flag">Weaker evidence</span>The bus leg is published already averaged over a month, a weekday and an hour, which hides the worst buses.`);
  }
  if (state.airport === "EWR") {
    notes.push(
      `<span class="flag">Car only</span>You can reach Newark by train — New Jersey ` +
      `Transit runs to the airport station in about 24 minutes — but the last mile ` +
      `cannot be quoted right now. The AirTrain there is being rebuilt through 2030 ` +
      `and is replaced by a shuttle bus on most weekday mornings, on a schedule that ` +
      `shifts with the season. A number here would be wrong by next month.`
    );
  }
  if (notes.length) {
    const evidence = document.createElement("div");
    evidence.className = "evidence";
    evidence.innerHTML = notes.map((n) => `<p>${n}</p>`).join("");
    detail.appendChild(evidence);
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
  const money = cell.fare == null ? "" : ` · ${formatFare(cell.fare)}`;
  figure.textContent = `${cell.p50} typical · ${cell.p90} on a bad day${money}`;
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

/* Car fares are a median across every service tier, because these records have
 * no column separating UberX from XL or Black. Live weekday quotes from Herald
 * Square at 5pm were $110 for an UberX and $150 for an XL, against a measured
 * $124 for that zone - the median sits between them, which is what an all-tiers
 * median should do. It is a real figure and it is nobody's quote, so the page
 * says so beneath the bars. */
function formatFare(value) {
  if (value == null) return "";
  return value === 0 ? "free" : `$${Number(value).toFixed(2).replace(/\.00$/, "")}`;
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

/* The then-and-now rows, filled from the measured cell.
 *
 * Sample size is printed beside each one because the two modes are not equally
 * common on this route: ride-hail runs it a few hundred times over the window,
 * yellow cabs a few dozen. A reader deserves to see which median is thin. */
function fillEras(todd) {
  const scale = 90;
  const rows = {
    todd: { minutes: todd.todd_minutes, note: "Measured by Todd Schneider from 1.1 billion trips." },
  };
  for (const [source, values] of Object.entries(todd.modes || {})) {
    // Derived from the month list rather than read from a field, so an older
    // todd.json without one still labels itself correctly.
    const span = describeMonths(values.months);
    rows[source] = {
      minutes: values.median,
      note: `${values.trips.toLocaleString()} trips, ${span}.`,
      window: span,
    };
  }

  for (const [era, row] of Object.entries(rows)) {
    const node = document.querySelector(`[data-era="${era}"]`);
    if (!node || row.minutes == null) continue;
    node.querySelector(".tn-fill").dataset.width = String(
      Math.min(100, (row.minutes / scale) * 100)
    );
    const value = node.querySelector(".tn-value");
    value.dataset.count = String(row.minutes);
    value.textContent = String(row.minutes);
    node.querySelector(".tn-note").textContent = row.note;
    if (era !== "todd" && row.window) {
      node.querySelector(".tn-when").textContent =
        `${era === "fhvhv" ? "Uber and Lyft" : "Yellow cab"}, ${row.window}`;
    }
  }

  const note = el("todd-note");
  if (note) {
    const ride = todd.modes && todd.modes.fhvhv;
    note.textContent = ride
      ? `All three are the same cell: Midtown Center to JFK, leaving between ` +
        `${todd.hour} and ${todd.hour + 1} in the morning, weekdays only. Todd's ` +
        `figure averages ${todd.todd_window}, so read the gap as a decade of ` +
        `drift rather than a single event — ride-hail growth, delivery traffic ` +
        `and street redesign all sit inside it. The rest of this page uses the ` +
        `full corpus of ${state.data.built_from.car.weekday_trips.toLocaleString()} ` +
        `weekday trips.`
      : "";
  }
}

/* "2026-01".."2026-05" -> "Jan to May 2026". A date range a reader can hold. */
function describeMonths(months) {
  if (!months || !months.length) return "";
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const part = (m) => {
    const [y, mm] = m.split("-");
    return { year: y, name: names[Number(mm) - 1] };
  };
  const first = part(months[0]);
  const last = part(months[months.length - 1]);
  if (months.length === 1) return `${first.name} ${first.year}`;
  if (first.year === last.year) return `${first.name} to ${last.name} ${first.year}`;
  return `${first.name} ${first.year} to ${last.name} ${last.year}`;
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
