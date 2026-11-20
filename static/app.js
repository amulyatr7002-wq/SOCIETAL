(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { user: null, csrf: "", complaints: [], teams: [], activeView: "overview", pendingAction: null, map: null, markers: [], pickMap: null, pickMarker: null, location: null, charts: {} };
  const categoryIcons = { Roads: "⌁", Water: "≈", Streetlights: "✦", Waste: "♧", Drainage: "⌇", Other: "✳" };

  function escapeHtml(value = "") {
    return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }
  function toast(message, error = false) {
    const node = document.createElement("div");
    node.className = `toast${error ? " error" : ""}`;
    node.textContent = message;
    $("#toast-region").append(node);
    setTimeout(() => node.remove(), 3600);
  }
  async function refreshCsrf() {
    const response = await fetch("/api/config");
    const data = await response.json();
    state.csrf = data.csrf_token;
  }
  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== "GET") headers.set("X-CSRF-Token", state.csrf);
    const response = await fetch(url, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  }
  const isAdmin = () => state.user?.role === "admin";
  const isResponder = () => state.user?.role === "responder";
  const roleLabel = role => ({ citizen: "Neighbour", admin: "Administrator", responder: "Response team" }[role] || "Community member");
  const formatDate = value => value ? new Date(value.replace(" ", "T") + (value.includes("Z") ? "" : "Z")).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
  const statusClass = status => `status-${status.toLowerCase().replaceAll(" ", "-")}`;
  const priorityClass = priority => `priority-${priority.toLowerCase()}`;
  const locationText = report => report.location_name || `${Number(report.latitude).toFixed(4)}, ${Number(report.longitude).toFixed(4)}`;

  function showLanding() {
    $$(".site-header, main > section:not(.app-shell), .site-footer").forEach(el => el.classList.remove("hidden"));
    $("#app-shell").classList.add("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function showWorkspace() {
    $$(".site-header, main > section:not(.app-shell), .site-footer").forEach(el => el.classList.add("hidden"));
    $("#app-shell").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    configureWorkspace();
  }
  function setView(view) {
    state.activeView = view;
    $$(".dashboard-view").forEach(section => section.classList.toggle("hidden", section.id !== `view-${view}`));
    $$(".side-link").forEach(button => button.classList.toggle("active", button.dataset.view === view));
    $("#view-title").textContent = ({ overview: "Overview", reports: isResponder() ? "Assigned reports" : "My reports", map: "Neighbourhood map", analytics: "Analytics" })[view] || "Overview";
    if (view === "map") setTimeout(renderMap, 80);
    if (view === "analytics") loadAnalytics();
  }
  function configureWorkspace() {
    $("#profile-name").textContent = state.user.name;
    $("#profile-role").textContent = roleLabel(state.user.role);
    $("#profile-avatar").textContent = state.user.name.split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase();
    $$(".admin-only").forEach(el => el.classList.toggle("hidden", !isAdmin()));
    $(".nav-report-label").textContent = isResponder() ? "Assigned reports" : "My reports";
    $("#welcome-title").innerHTML = `${isAdmin() ? "Good morning, " : "Good morning, "}${escapeHtml(state.user.name.split(" ")[0])} <span>✳</span>`;
    $("#welcome-eyebrow").textContent = isAdmin() ? "CIVIC OPERATIONS DASHBOARD" : isResponder() ? "YOUR RESPONSE TEAM" : "YOUR COMMUNITY, IN THE LOOP";
    $("#welcome-description").textContent = isAdmin() ? "Here’s the latest view of civic reports and response progress." : isResponder() ? "Here are the community reports assigned to your response team." : "Here’s what’s happening around your neighbourhood today.";
    $("#reports-eyebrow").textContent = isAdmin() ? "CITY OPERATIONS" : isResponder() ? "YOUR RESPONSE QUEUE" : "YOUR NEIGHBOURHOOD";
    $("#reports-title").textContent = isAdmin() ? "All reports" : isResponder() ? "Assigned reports" : "My reports";
    $("#reports-description").textContent = isAdmin() ? "Review, prioritize and coordinate neighbourhood response." : isResponder() ? "Update progress on work assigned to your team." : "Follow every update from report to resolution.";
    $("#today-date").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
    setView(state.activeView);
    refreshWorkspace();
  }
  async function refreshWorkspace() {
    try {
      const data = await api("/api/complaints");
      state.complaints = data.complaints;
      state.teams = data.teams;
      renderDashboard();
      if (state.activeView === "map") renderMap();
      if (state.activeView === "analytics" && isAdmin()) loadAnalytics();
    } catch (error) { toast(error.message, true); }
  }
  function renderDashboard() {
    $("#nav-count").textContent = state.complaints.length;
    const resolved = state.complaints.filter(item => ["Resolved", "Closed"].includes(item.status)).length;
    const open = state.complaints.filter(item => !["Resolved", "Closed"].includes(item.status)).length;
    const critical = state.complaints.filter(item => item.priority.label === "Critical").length;
    const metrics = isAdmin() ? [
      ["All reports", state.complaints.length, "Across all neighbourhoods", "▤", "blue"],
      ["Need attention", open, "Still in the response queue", "◷", "orange"],
      ["Critical priority", critical, "Urgent community needs", "✳", "purple"],
      ["Resolved", resolved, "Reports completed", "✓", "green"],
    ] : isResponder() ? [
      ["Assigned to team", state.complaints.length, "Reports in your queue", "▤", "blue"],
      ["In progress", state.complaints.filter(item => item.status === "In Progress").length, "Work underway", "◷", "orange"],
      ["High priority", state.complaints.filter(item => ["Critical", "High"].includes(item.priority.label)).length, "Needs close attention", "✳", "purple"],
      ["Resolved", resolved, "Completed by team", "✓", "green"],
    ] : [
      ["Your reports", state.complaints.length, "Every report you’ve shared", "▤", "blue"],
      ["Being worked on", state.complaints.filter(item => ["Assigned", "In Progress"].includes(item.status)).length, "Picked up by a local team", "◷", "orange"],
      ["Resolved", resolved, "Good things changed", "✓", "green"],
      ["Open reports", open, "Updates are on their way", "✳", "purple"],
    ];
    $("#metric-grid").innerHTML = metrics.map(([label, value, note, icon, tone]) => `<article class="metric-card"><div class="metric-head"><span>${label}</span><span class="metric-icon ${tone}">${icon}</span></div><div class="metric-value">${value}</div><div class="metric-note">${note}</div></article>`).join("");
    const latest = [...state.complaints].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 4);
    $("#recent-reports").innerHTML = latest.length ? latest.map(report => `<div class="recent-item" data-open-report="${report.public_id}"><span class="report-category-icon ${escapeHtml(report.category)}">${categoryIcons[report.category] || "✳"}</span><span class="recent-info"><strong class="recent-title">${escapeHtml(report.title)}</strong><small class="recent-sub">${escapeHtml(report.public_id)} · ${formatDate(report.created_at)}</small></span><span class="status-pill ${statusClass(report.status)}">${escapeHtml(report.status)}</span></div>`).join("") : `<div class="empty-state"><strong>Nothing to see just yet.</strong>Start by sharing a local issue.</div>`;
    $("#pulse-count").textContent = open;
    renderReports();
  }
  function reportControls(report) {
    const assign = isAdmin() ? `<select data-assign-select="${report.id}" aria-label="Assign response team"><option value="">${report.team_id ? escapeHtml(report.team_name) : "Assign a team"}</option>${state.teams.map(team => `<option value="${team.id}">${escapeHtml(team.name)}</option>`).join("")}</select><button class="button button-outline" data-assign="${report.id}">Assign</button>` : "";
    const priority = isAdmin() ? `<select data-priority-select="${report.id}" aria-label="Override priority"><option value="">Priority · ${escapeHtml(report.priority.label)}</option>${["Critical", "High", "Medium", "Low"].map(item => `<option value="${item}">${item}</option>`).join("")}</select><button class="button button-outline" data-priority="${report.id}">Set</button>` : "";
    const responder = isResponder() ? `<select data-status-select="${report.id}" aria-label="Update status"><option value="">Update status</option><option>In Progress</option><option>Resolved</option></select><button class="button button-outline" data-status="${report.id}">Update</button><label class="button button-outline upload-resolution">＋ Photo<input type="file" accept="image/jpeg,image/png,image/webp" data-resolution-photo="${report.id}" hidden></label>` : "";
    const adminStatus = isAdmin() ? `<select data-status-select="${report.id}" aria-label="Update status"><option value="">Status · ${escapeHtml(report.status)}</option>${["Submitted", "Under Review", "Assigned", "In Progress", "Resolved", "Closed"].map(item => `<option>${item}</option>`).join("")}</select><button class="button button-outline" data-status="${report.id}">Update</button>` : "";
    return assign || priority || responder || adminStatus ? `<div class="admin-controls">${assign}${adminStatus}${priority}${responder}</div>` : "";
  }
  function reportCard(report) {
    return `<article class="report-card" data-open-report="${report.public_id}"><div class="report-card-top"><span class="report-category-icon ${escapeHtml(report.category)}">${categoryIcons[report.category] || "✳"}</span><div class="report-card-main"><h3>${escapeHtml(report.title)}</h3><span class="report-ref">${escapeHtml(report.public_id)} · ${escapeHtml(report.category)} · ${formatDate(report.created_at)}</span></div><span class="priority-badge ${priorityClass(report.priority.label)}">${escapeHtml(report.priority.label)}</span></div><p class="report-card-description">${escapeHtml(report.description)}</p><div class="report-card-footer"><span class="report-location">⌖ ${escapeHtml(locationText(report))}</span><span class="status-pill ${statusClass(report.status)}">${escapeHtml(report.status)}</span></div>${isAdmin() ? `<div class="report-ref">Reported by ${escapeHtml(report.citizen_name)} · ${escapeHtml(report.department_name || "Unassigned")}</div>` : ""}${reportControls(report)}</article>`;
  }
  function renderReports() {
    const search = ($("#report-search")?.value || "").trim().toLowerCase();
    const status = $("#filter-status")?.value || "";
    const category = $("#filter-category")?.value || "";
    const filtered = state.complaints.filter(report =>
      (!status || report.status === status) &&
      (!category || report.category === category) &&
      (!search || `${report.title} ${report.public_id} ${report.location_name}`.toLowerCase().includes(search))
    );
    $("#reports-list").innerHTML = filtered.length ? filtered.map(reportCard).join("") : `<div class="empty-state"><strong>No matching reports.</strong>Try adjusting your filters or add a new report.</div>`;
  }
  async function openDetail(publicId) {
    try {
      const { complaint: report } = await api(`/api/complaints/${encodeURIComponent(publicId)}`);
      const history = report.history.length ? report.history.map(item => `<div class="history-item"><strong>${escapeHtml(item.status)} <small>· ${escapeHtml(item.changed_by)}</small></strong><small>${escapeHtml(item.note)} · ${formatDate(item.created_at)}</small></div>`).join("") : `<div class="history-item"><strong>Report received</strong><small>${formatDate(report.created_at)}</small></div>`;
      const images = report.images.map(image => `<a href="${image.url}" target="_blank" rel="noopener"><img src="${image.url}" alt="${image.kind === "resolution" ? "Resolution photo" : "Issue photo"}"></a>`).join("");
      const contributions = report.priority.breakdown;
      const controls = reportControls(report);
      $("#detail-content").innerHTML = `<div class="detail-head"><span class="eyebrow">${escapeHtml(report.public_id)} · ${escapeHtml(report.category)}</span><h2>${escapeHtml(report.title)}</h2><div class="detail-meta"><span class="status-pill ${statusClass(report.status)}">${escapeHtml(report.status)}</span><span class="priority-badge ${priorityClass(report.priority.label)}">${escapeHtml(report.priority.label)} · ${report.priority.score}/100</span><span>Reported ${formatDate(report.created_at)}</span></div></div><p class="detail-description">${escapeHtml(report.description)}</p><div class="detail-meta">⌖ ${escapeHtml(locationText(report))} ${report.team_name ? `· ${escapeHtml(report.team_name)}` : ""}</div><div class="detail-section-title">Priority score explained</div><div class="detail-meta">Severity ${contributions.severity}/50 · Nearby reports ${contributions.nearby_reports}/30 (${contributions.similar_reports_within_1km} within 1 km) · Time elapsed ${contributions.time_elapsed}/20</div>${images ? `<div class="detail-section-title">Photos</div><div class="detail-images">${images}</div>` : ""}<div class="detail-section-title">Progress timeline</div><div class="history-list">${history}</div>${isAdmin() || isResponder() ? `<div class="detail-section-title">Response actions</div>${controls}<form class="resolution-upload-form" data-resolution-form="${report.id}"><label class="form-field">Resolution photo<input type="file" name="image" accept="image/jpeg,image/png,image/webp" required></label><button class="button button-outline">Upload photo</button></form>` : ""}`;
      $("#detail-modal").showModal();
    } catch (error) { toast(error.message, true); }
  }

  function openAuth(mode = "login") {
    state.pendingAction = null;
    setAuthMode(mode);
    $("#auth-error").textContent = "";
    $("#auth-modal").showModal();
  }
  function setAuthMode(mode) {
    const register = mode === "register";
    $("#auth-title").textContent = register ? "Make yourself at home." : "Good things start here.";
    $("#auth-subtitle").textContent = register ? "Create an account to join your community." : "Sign in to be part of what happens next.";
    $$(".auth-tab").forEach(tab => tab.classList.toggle("active", tab.dataset.authTab === mode));
    $$(".register-field").forEach(field => field.classList.toggle("hidden", !register));
    $("#auth-form").dataset.mode = mode;
    $("#auth-form").elements.password.autocomplete = register ? "new-password" : "current-password";
    $("#auth-submit").innerHTML = `${register ? "Create my account" : "Log in"} <span>→</span>`;
  }
  function openReport() {
    if (!state.user) { openAuth("login"); state.pendingAction = "report"; return; }
    if (state.user.role !== "citizen") { toast("Issue reports are submitted from a citizen account.", true); return; }
    $("#report-error").textContent = "";
    $("#report-form").reset();
    $("#upload-file-name").textContent = "Choose image";
    state.location = null;
    if (state.pickMarker && state.pickMap) state.pickMap.removeLayer(state.pickMarker);
    state.pickMarker = null;
    $("#location-status").textContent = "Click on the map to drop a pin.";
    $("#report-modal").showModal();
    setTimeout(initPickMap, 120);
  }
  function initPickMap() {
    if (!window.L || !$("#pick-map")) return;
    if (!state.pickMap) {
      state.pickMap = L.map("pick-map").setView([12.9716, 77.5946], 14);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(state.pickMap);
      state.pickMap.on("click", event => {
        state.location = event.latlng;
        if (state.pickMarker) state.pickMarker.setLatLng(event.latlng);
        else state.pickMarker = L.marker(event.latlng).addTo(state.pickMap);
        $("#location-status").textContent = `Pinned at ${event.latlng.lat.toFixed(5)}, ${event.latlng.lng.toFixed(5)}`;
      });
    }
    state.pickMap.invalidateSize();
  }
  function markerColor(report) {
    if (report.priority.label === "Critical") return "#d96060";
    return ({ Roads: "#4b8dd3", Water: "#42a7ae", Streetlights: "#dfa448", Waste: "#54a77b", Drainage: "#788ac7", Other: "#9a77ba" })[report.category] || "#558cc5";
  }
  function renderMap() {
    if (!window.L || !$("#full-map") || $("#view-map").classList.contains("hidden")) return;
    if (!state.map) {
      state.map = L.map("full-map").setView([12.9716, 77.5946], 13);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(state.map);
    }
    state.map.invalidateSize();
    state.markers.forEach(layer => state.map.removeLayer(layer));
    state.markers = [];
    state.hotspotKeys = new Set();
    const filter = $("#map-category-filter").value;
    const reports = state.complaints.filter(report => !filter || report.category === filter);
    reports.forEach(report => {
      const marker = L.circleMarker([report.latitude, report.longitude], {
        radius: report.priority.label === "Critical" ? 9 : 7, color: "#fff", weight: 2,
        fillColor: markerColor(report), fillOpacity: .95,
      }).bindPopup(`<div class="popup-title">${escapeHtml(report.title)}</div><div class="popup-sub">${escapeHtml(report.category)} · ${escapeHtml(report.public_id)}<br>${escapeHtml(locationText(report))}</div><span class="popup-status">${escapeHtml(report.status)} · ${escapeHtml(report.priority.label)} priority</span>`);
      marker.on("click", () => { state.map.once("popupopen", () => { const link = document.querySelector(".leaflet-popup-content"); if (link) link.addEventListener("click", () => openDetail(report.public_id)); }); });
      marker.addTo(state.map);
      state.markers.push(marker);
    });
    // Close report clusters are shown as subtle rings to reveal local hotspots.
    for (let i = 0; i < reports.length; i++) {
      let neighbours = 0;
      for (let j = 0; j < reports.length; j++) {
        if (i !== j && distanceKm(reports[i], reports[j]) <= 1) neighbours++;
      }
      if (neighbours >= 2 && !state.hotspotKeys?.has(reports[i].public_id)) {
        if (!state.hotspotKeys) state.hotspotKeys = new Set();
        state.hotspotKeys.add(reports[i].public_id);
        const ring = L.circle([reports[i].latitude, reports[i].longitude], { radius: 400, color: "#ed926f", weight: 1, fillColor: "#f6b49b", fillOpacity: .12, interactive: false });
        ring.addTo(state.map);
        state.markers.push(ring);
      }
    }
    if (reports.length && !state.mapCentered) {
      const group = L.featureGroup(state.markers.filter(item => item.getLatLng));
      if (group.getLayers().length) state.map.fitBounds(group.getBounds().pad(.15), { maxZoom: 14 });
      state.mapCentered = true;
    }
  }
  function distanceKm(a, b) {
    const r = Math.PI / 180;
    const dLat = (b.latitude - a.latitude) * r;
    const dLng = (b.longitude - a.longitude) * r;
    const v = Math.sin(dLat / 2) ** 2 + Math.cos(a.latitude * r) * Math.cos(b.latitude * r) * Math.sin(dLng / 2) ** 2;
    return 6371 * 2 * Math.atan2(Math.sqrt(v), Math.sqrt(1 - v));
  }
  async function loadAnalytics() {
    if (!isAdmin()) return;
    try {
      const data = await api("/api/analytics");
      const totals = data.totals;
      $("#analytics-metrics").innerHTML = [
        ["All reports", totals.total, "Reports recorded", "▤", "blue"],
        ["Pending", totals.pending, "Awaiting resolution", "◷", "orange"],
        ["Critical", totals.critical, "Priority attention", "✳", "purple"],
        ["Resolved", totals.resolved, `Avg. resolution ${totals.average_resolution_hours ?? "—"}h`, "✓", "green"],
      ].map(([label, value, note, icon, tone]) => `<article class="metric-card"><div class="metric-head"><span>${label}</span><span class="metric-icon ${tone}">${icon}</span></div><div class="metric-value">${value}</div><div class="metric-note">${note}</div></article>`).join("");
      makeChart("category-chart", "doughnut", data.categories.map(row => row.label), data.categories.map(row => row.value), ["#4388d0", "#52aab4", "#e7ae54", "#65ad80", "#758dc8", "#a37fc1"]);
      makeChart("monthly-chart", "line", data.monthly.map(row => row.label), data.monthly.map(row => row.value), ["#4388d0"]);
      makeChart("area-chart", "bar", data.areas.map(row => row.label), data.areas.map(row => row.value), ["#5d9bd6"]);
      $("#department-list").innerHTML = data.departments.map(row => {
        const total = Number(row.total) || 0;
        const resolvedCount = Number(row.resolved) || 0;
        const rate = total ? Math.round(resolvedCount / total * 100) : 0;
        return `<div class="department-row"><span class="department-icon">⌂</span><span class="department-name">${escapeHtml(row.label)}<small>${resolvedCount} resolved · ${total} assigned</small></span><span class="department-completion">${rate}%</span></div>`;
      }).join("") || `<div class="empty-state">No department assignments yet.</div>`;
    } catch (error) { toast(error.message, true); }
  }
  function makeChart(id, type, labels, values, colors) {
    const canvas = $(`#${id}`);
    if (!canvas || !window.Chart) return;
    if (state.charts[id]) state.charts[id].destroy();
    state.charts[id] = new Chart(canvas, {
      type,
      data: { labels, datasets: [{ data: values, backgroundColor: type === "doughnut" ? colors : `${colors[0]}22`, borderColor: colors[0], borderWidth: type === "doughnut" ? 0 : 2, borderRadius: type === "bar" ? 5 : 0, fill: type === "line", tension: .35, pointRadius: 3, pointBackgroundColor: colors[0] }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: type === "doughnut", position: "bottom", labels: { color: "#80909b", usePointStyle: true, boxWidth: 7, font: { size: 9 } } } },
        scales: type === "doughnut" ? {} : { x: { grid: { display: false }, ticks: { color: "#91a0aa", font: { size: 8 } } }, y: { beginAtZero: true, grid: { color: "#eff3f6" }, ticks: { color: "#91a0aa", precision: 0, font: { size: 8 } } } },
      },
    });
  }
  async function openTrack(ref = "") {
    $("#track-result").innerHTML = "";
    $("#track-form").elements.reference.value = ref;
    $("#track-modal").showModal();
    if (ref && state.user) trackReference(ref);
  }
  async function trackReference(ref) {
    try {
      const { complaint } = await api(`/api/complaints/${encodeURIComponent(ref.trim())}`);
      $("#track-result").innerHTML = `<div class="track-result-card"><strong>${escapeHtml(complaint.title)}</strong><p>${escapeHtml(complaint.public_id)} · ${escapeHtml(complaint.category)} · ${formatDate(complaint.updated_at)}</p><span class="status-pill ${statusClass(complaint.status)}">${escapeHtml(complaint.status)}</span><p>${escapeHtml(complaint.history.at(-1)?.note || "Report received.")}</p></div>`;
    } catch (error) {
      $("#track-result").innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`;
    }
  }
  async function uploadResolution(complaintId, file) {
    const body = new FormData();
    body.append("image", file);
    try {
      await api(`/api/complaints/${complaintId}/resolution-image`, { method: "POST", body });
      toast("Resolution photo added.");
      await refreshWorkspace();
    } catch (error) { toast(error.message, true); }
  }
  async function handleAssignment(button) {
    const scope = button.closest(".report-card") || $("#detail-content");
    const teamId = $(`[data-assign-select="${button.dataset.assign}"]`, scope).value;
    if (!teamId) return toast("Choose a response team first.", true);
    try {
      const result = await api(`/api/complaints/${button.dataset.assign}/assign`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ team_id: teamId }) });
      toast(result.message);
      await refreshWorkspace();
    } catch (error) { toast(error.message, true); }
  }
  async function handleStatus(button) {
    const scope = button.closest(".report-card") || $("#detail-content");
    const select = $(`[data-status-select="${button.dataset.status}"]`, scope);
    if (!select.value) return toast("Choose a status first.", true);
    try {
      const result = await api(`/api/complaints/${button.dataset.status}/status`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: select.value }) });
      toast(result.message);
      await refreshWorkspace();
      if ($("#detail-modal").open) {
        const item = state.complaints.find(report => report.id === Number(button.dataset.status));
        $("#detail-modal").close();
        if (item) await openDetail(item.public_id);
      }
    } catch (error) { toast(error.message, true); }
  }

  document.addEventListener("click", async event => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "login" || action === "register") openAuth(action);
    if (action === "report") openReport();
    if (action === "track") openTrack();
    if (action === "logout") {
      try {
        await api("/api/logout", { method: "POST" });
        state.user = null;
        state.csrf = "";
        showLanding();
        await refreshCsrf();
        toast("You’re signed out. See you soon.");
      } catch (error) { toast(error.message, true); }
    }
    if (action === "close-modal") event.target.closest("dialog").close();
    if (action === "menu") $(".main-nav").classList.toggle("open");
    if (action === "notifications") {
      try {
        const data = await api("/api/notifications");
        await api("/api/notifications/read", { method: "POST" });
        $("#notification-dot").style.display = "none";
        toast(data.notifications.length ? data.notifications[0].message : "You’re all caught up.");
      } catch (error) { toast(error.message, true); }
    }
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) {
      const view = viewButton.dataset.view;
      if (view === "analytics" && !isAdmin()) return toast("Analytics are available to administrators.", true);
      setView(view);
      if (innerWidth < 760) $("#app-shell").scrollIntoView({ behavior: "smooth" });
    }
    if (event.target.closest("[data-home]")) {
      event.preventDefault();
      state.user ? (state.activeView = "overview", showWorkspace()) : showLanding();
    }
    const categoryButton = event.target.closest("[data-category]");
    if (categoryButton) {
      openReport();
      if (state.user?.role === "citizen") $("#report-form").elements.category.value = categoryButton.dataset.category;
    }
    const reportTarget = event.target.closest("[data-open-report]");
    if (reportTarget && !event.target.closest(".admin-controls")) openDetail(reportTarget.dataset.openReport);
    const assignButton = event.target.closest("[data-assign]");
    if (assignButton) handleAssignment(assignButton);
    const statusButton = event.target.closest("[data-status]");
    if (statusButton) handleStatus(statusButton);
    const priorityButton = event.target.closest("[data-priority]");
    if (priorityButton) {
      const scope = priorityButton.closest(".report-card") || $("#detail-content");
      const priority = $(`[data-priority-select="${priorityButton.dataset.priority}"]`, scope).value;
      if (!priority) return toast("Choose a priority first.", true);
      try {
        const result = await api(`/api/complaints/${priorityButton.dataset.priority}/priority`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ priority }) });
        toast(result.message);
        await refreshWorkspace();
      } catch (error) { toast(error.message, true); }
    }
    const photo = event.target.closest("[data-resolution-photo]");
    if (photo?.files?.[0]) uploadResolution(photo.dataset.resolutionPhoto, photo.files[0]);
  });
  $$(".auth-tab").forEach(tab => tab.addEventListener("click", () => setAuthMode(tab.dataset.authTab)));
  $("#auth-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const mode = form.dataset.mode;
    const payload = Object.fromEntries(new FormData(form));
    $("#auth-error").textContent = "";
    try {
      if (mode === "register") {
        await api("/api/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        toast("Account created. Sign in to continue.");
        setAuthMode("login");
        form.elements.email.value = payload.email;
        form.elements.password.value = "";
      } else {
        const data = await api("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        state.user = data.user;
        await refreshCsrf();
        $("#auth-modal").close();
        state.activeView = "overview";
        showWorkspace();
        if (state.pendingAction === "report") setTimeout(openReport, 180);
        state.pendingAction = null;
        toast(`Welcome in, ${state.user.name.split(" ")[0]}.`);
        if (state.pendingTrack) {
          const ref = state.pendingTrack;
          state.pendingTrack = null;
          openTrack(ref);
        }
      }
    } catch (error) { $("#auth-error").textContent = error.message; }
  });
  $("#report-form").addEventListener("submit", async event => {
    event.preventDefault();
    $("#report-error").textContent = "";
    if (!state.location) return $("#report-error").textContent = "Choose the issue location on the map before submitting.";
    const formData = new FormData(event.currentTarget);
    formData.set("latitude", state.location.lat);
    formData.set("longitude", state.location.lng);
    try {
      const result = await api("/api/complaints", { method: "POST", body: formData });
      $("#report-modal").close();
      toast(`Report submitted · ${result.complaint_id}`);
      state.activeView = "reports";
      await refreshWorkspace();
      setView("reports");
      showWorkspace();
    } catch (error) { $("#report-error").textContent = error.message; }
  });
  $("#report-form").elements.image.addEventListener("change", event => {
    $("#upload-file-name").textContent = event.target.files[0]?.name || "Choose image";
  });
  $("#track-form").addEventListener("submit", event => {
    event.preventDefault();
    if (!state.user) {
      const ref = event.currentTarget.elements.reference.value.trim();
      state.pendingAction = null;
      $("#track-modal").close();
      openAuth("login");
      setTimeout(() => { state.pendingTrack = ref; }, 0);
      return;
    }
    trackReference(event.currentTarget.elements.reference.value);
  });
  $("#report-search").addEventListener("input", renderReports);
  $("#filter-status").addEventListener("change", renderReports);
  $("#filter-category").addEventListener("change", renderReports);
  $("#map-category-filter").addEventListener("change", () => {
    state.hotspotKeys = new Set();
    renderMap();
  });
  $$(".main-nav a").forEach(link => link.addEventListener("click", () => $(".main-nav").classList.remove("open")));
  $("#detail-content").addEventListener("submit", async event => {
    if (!event.target.matches("[data-resolution-form]")) return;
    event.preventDefault();
    const formData = new FormData(event.target);
    try {
      await api(`/api/complaints/${event.target.dataset.resolutionForm}/resolution-image`, { method: "POST", body: formData });
      toast("Resolution photo uploaded.");
      await refreshWorkspace();
      const item = state.complaints.find(report => report.id === Number(event.target.dataset.resolutionForm));
      if (item) openDetail(item.public_id);
    } catch (error) { toast(error.message, true); }
  });
  async function boot() {
    try {
      await refreshCsrf();
      const data = await api("/api/me");
      state.user = data.user;
      if (state.user) showWorkspace();
      else showLanding();
      if (state.pendingTrack) {
        const ref = state.pendingTrack;
        state.pendingTrack = null;
        openTrack(ref);
      }
    } catch (error) { toast(error.message, true); }
  }
  boot();
})();
