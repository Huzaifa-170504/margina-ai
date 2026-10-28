let sessionState = null;
let activeMembership = null;

const organizationSelect = document.querySelector("#organization");
const branchSelect = document.querySelector("#workspace-branch");
const statusBanner = document.querySelector("#workspace-status");
const financialView = document.querySelector("#financial-view");
const roleNotice = document.querySelector("#role-notice");
const money = new Intl.NumberFormat("en-PK", {
  style: "currency",
  currency: "PKR",
  maximumFractionDigits: 0,
});

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    window.location.replace("/login");
    throw new Error("Your session has expired.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error?.message || "The workspace request failed.");
  return body;
}

async function initialize() {
  try {
    sessionState = await fetchJson("/api/v1/auth/me");
    if (!sessionState.memberships.length) throw new Error("Your account has no active organization membership.");
    document.querySelector("#user-email").textContent = sessionState.user.email;
    for (const membership of sessionState.memberships) {
      const option = document.createElement("option");
      option.value = membership.tenant_id;
      option.textContent = membership.organization_name;
      organizationSelect.append(option);
    }
    selectMembership();
    await loadWorkspace();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function selectMembership() {
  activeMembership = sessionState.memberships.find((item) => item.tenant_id === organizationSelect.value)
    || sessionState.memberships[0];
  organizationSelect.value = activeMembership.tenant_id;
  document.querySelector("#role-badge").textContent = activeMembership.role;
  document.querySelector("#branch-scope").textContent = activeMembership.branch_scope.length
    ? `Authorized branches: ${activeMembership.branch_scope.join(", ")}`
    : "Authorized for all branches";
  document.querySelector("#workspace-subtitle").textContent = `${activeMembership.organization_name} · ${roleLabel(activeMembership.role)}`;
}

async function loadWorkspace() {
  setStatus("Loading your authorized published snapshot…");
  const tenant = encodeURIComponent(activeMembership.tenant_id);
  const query = branchSelect.value ? `?branch=${encodeURIComponent(branchSelect.value)}` : "";
  const canViewFinancial = ["finance", "analyst"].includes(activeMembership.role);
  financialView.hidden = !canViewFinancial;
  roleNotice.hidden = canViewFinancial;
  if (!canViewFinancial) {
    roleNotice.textContent = activeMembership.role === "operations"
      ? "Your operations role can inspect process evidence. Financial records require a finance or analyst membership."
      : "Your administrator role manages access and publication. Financial records require a finance or analyst membership."
  }

  try {
    const processPromise = fetchJson(`/api/v1/organizations/${tenant}/dashboard/process${query}`);
    const financialPromise = canViewFinancial
      ? Promise.all([
        fetchJson(`/api/v1/organizations/${tenant}/dashboard/summary${query}`),
        fetchJson(`/api/v1/organizations/${tenant}/dashboard/orders${query}`),
      ])
      : Promise.resolve(null);
    const [process, financial] = await Promise.all([processPromise, financialPromise]);
    populateBranches(process.available_branches);
    renderWorkspaceProcess(process);
    if (financial) {
      renderWorkspaceSummary(financial[0]);
      renderWorkspaceOrders(financial[1].orders);
    }
    setStatus("Authorized published snapshot loaded.", "ready");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function populateBranches(branches) {
  const selected = branchSelect.value;
  branchSelect.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All authorized branches";
  branchSelect.append(all);
  for (const branch of branches) {
    const option = document.createElement("option");
    option.value = branch;
    option.textContent = branch;
    branchSelect.append(option);
  }
  if (branches.includes(selected)) branchSelect.value = selected;
}

function renderWorkspaceSummary(summary) {
  setText("#workspace-revenue", money.format(summary.metrics.net_revenue));
  setText("#workspace-gross-profit", money.format(summary.metrics.gross_profit));
  setText("#workspace-contribution", money.format(summary.metrics.contribution));
  setText(
    "#workspace-margin",
    summary.metrics.contribution_margin === null
      ? "Undefined"
      : `${(Number(summary.metrics.contribution_margin) * 100).toFixed(1)}%`,
  );
  setText("#workspace-order-count", `${summary.coverage.financial_orders} authorized orders`);
  setText("#workspace-cost-coverage", `Cost coverage ${summary.coverage.cost_coverage_percent}%`);
  setText("#workspace-snapshot", `Snapshot ${summary.snapshot_id.slice(0, 8)}… · metric ${summary.metric_version}`);
}

function renderWorkspaceOrders(orders) {
  const body = document.querySelector("#workspace-orders");
  body.replaceChildren();
  if (!orders.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 8;
    cell.className = "table-empty";
    cell.textContent = "No authorized orders match the active filters.";
    row.append(cell);
    body.append(row);
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

function renderWorkspaceProcess(process) {
  setText("#workspace-median", process.median_cycle_hours ?? "—");
  setText("#workspace-p90", process.p90_cycle_hours ?? "—");
  setText("#workspace-process-note", process.limitation);
  const container = document.querySelector("#workspace-transitions");
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
    const meta = document.createElement("div");
    meta.className = "transition-meta";
    meta.textContent = `${transition.count} cases · median ${transition.median_hours} h`;
    row.append(label, progress, meta);
    container.append(row);
  }
}

organizationSelect.addEventListener("change", async () => {
  branchSelect.value = "";
  selectMembership();
  await loadWorkspace();
});
branchSelect.addEventListener("change", loadWorkspace);
document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    await fetchJson("/api/v1/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": sessionState.csrf_token },
    });
  } finally {
    window.location.replace("/login");
  }
});

initialize();

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

function roleLabel(role) {
  return {
    finance: "Finance workspace",
    analyst: "Analyst workspace",
    operations: "Operations workspace",
    administrator: "Administration workspace",
  }[role] || role;
}
