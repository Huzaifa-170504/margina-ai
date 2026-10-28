const branchSelect = document.querySelector("#branch");
const statusBanner = document.querySelector("#dashboard-status");
const money = new Intl.NumberFormat("en-PK", {
  style: "currency",
  currency: "PKR",
  maximumFractionDigits: 0,
});

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error?.message || "The dashboard request failed.");
  return body;
}

async function loadDashboard() {
  setStatus("Loading published snapshot…");
  const query = branchSelect.value ? `?branch=${encodeURIComponent(branchSelect.value)}` : "";
  try {
    const [summary, evidence, process] = await Promise.all([
      fetchJson(`/api/v1/demo/summary${query}`),
      fetchJson(`/api/v1/demo/orders${query}`),
      fetchJson(`/api/v1/demo/process${query}`),
    ]);
    populateBranches(summary.available_branches);
    renderSummary(summary);
    renderOrders(evidence.orders);
    renderProcess(process);
    setStatus("Published snapshot loaded.", "ready");
  } catch (error) {
    setStatus(error.message, "error");
    renderEmptyOrders(error.message);
  }
}

function populateBranches(branches) {
  if (branchSelect.options.length > 1) return;
  for (const branch of branches) {
    const option = document.createElement("option");
    option.value = branch;
    option.textContent = branch;
    branchSelect.append(option);
  }
}

function renderSummary(summary) {
  setText("#snapshot-id", shortId(summary.snapshot_id));
  setText("#metric-version", summary.metric_version);
  setText("#published-at", formatDate(summary.published_at));
  setText("#source-freshness", formatDate(summary.freshness.latest_source_event_at));
  setText("#net-revenue", money.format(summary.metrics.net_revenue));
  setText("#contribution", money.format(summary.metrics.contribution));
  setText(
    "#margin",
    summary.metrics.contribution_margin === null
      ? "Undefined"
      : `${(Number(summary.metrics.contribution_margin) * 100).toFixed(1)}%`,
  );
  setText("#coverage", `Cost coverage ${summary.coverage.cost_coverage_percent}%`);
  setText(
    "#median-cycle",
    summary.process.median_cycle_hours === null ? "Undefined" : `${summary.process.median_cycle_hours} h`,
  );
  setText("#process-coverage", `Process coverage ${summary.coverage.process_coverage_percent}%`);
  setText("#sla-count", summary.process.sla_breach_count);
  setText("#loop-count", summary.process.approval_loop_count);
}

function renderOrders(orders) {
  const body = document.querySelector("#orders");
  body.replaceChildren();
  setText("#order-count", `${orders.length} orders in the active cohort`);
  if (!orders.length) {
    renderEmptyOrders("No orders match the active filters.");
    return;
  }
  for (const order of orders) {
    const row = document.createElement("tr");
    addCell(row, order.order_id);
    addCell(row, order.branch_id);
    addCell(row, money.format(order.net_revenue));
    addCell(row, money.format(order.recognized_cogs));
    addCell(row, money.format(order.variable_costs));
    addCell(row, money.format(order.contribution));
    addCell(row, order.cycle_hours === null ? "Incomplete" : `${order.cycle_hours} h`);
    const signals = document.createElement("td");
    if (order.sla_breach) signals.append(createTag("SLA breach"));
    if (order.approval_loop) signals.append(createTag("Approval loop"));
    if (!order.sla_breach && !order.approval_loop) signals.append(createTag("No flag", true));
    row.append(signals);
    body.append(row);
  }
}

function renderEmptyOrders(message) {
  const body = document.querySelector("#orders");
  body.replaceChildren();
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = 8;
  cell.className = "table-empty";
  cell.textContent = message;
  row.append(cell);
  body.append(row);
}

function renderProcess(process) {
  setText("#process-limitation", process.limitation);
  const container = document.querySelector("#transitions");
  container.replaceChildren();
  const maxCount = Math.max(1, ...process.transitions.map((item) => item.count));
  for (const transition of process.transitions) {
    const row = document.createElement("div");
    row.className = "transition-row";
    const label = document.createElement("div");
    label.className = "transition-label";
    label.textContent = `${transition.from} → ${transition.to}`;
    const progress = document.createElement("progress");
    progress.max = maxCount;
    progress.value = transition.count;
    progress.setAttribute("aria-label", `${transition.count} transitions`);
    const meta = document.createElement("div");
    meta.className = "transition-meta";
    meta.textContent = `${transition.count} cases · median ${transition.median_hours} h`;
    row.append(label, progress, meta);
    container.append(row);
  }
}

document.querySelector("#scenario-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.querySelector("#scenario-result");
  result.textContent = "Calculating…";
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const body = await fetchJson("/api/v1/demo/scenarios/shipping", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    result.textContent = `Estimated net savings: ${money.format(body.scenario.estimated_net_savings)}. ${body.disclaimer}`;
  } catch (error) {
    result.textContent = error.message;
  }
});

branchSelect.addEventListener("change", loadDashboard);
loadDashboard();

function setText(selector, value) {
  document.querySelector(selector).textContent = value ?? "—";
}

function setStatus(message, state = "loading") {
  statusBanner.textContent = message;
  statusBanner.className = `status-banner ${state}`;
}

function addCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  row.append(cell);
}

function createTag(label, neutral = false) {
  const tag = document.createElement("span");
  tag.className = neutral ? "tag tag-neutral" : "tag";
  tag.textContent = label;
  return tag;
}

function shortId(value) {
  return value ? `${value.slice(0, 8)}…` : "—";
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-PK", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
