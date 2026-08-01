const state = {
  apiKey: sessionStorage.getItem("smartmailer_api_key") || "",
  workspace: null,
  contacts: [],
  campaigns: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);
}

function safeEmailHtml(markup = "") {
  const parsed = new DOMParser().parseFromString(String(markup), "text/html");
  parsed.querySelectorAll("script, iframe, object, embed, form").forEach(node => node.remove());
  parsed.querySelectorAll("*").forEach(node => {
    [...node.attributes].forEach(attribute => {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim().toLowerCase();
      if (name.startsWith("on") || ((name === "href" || name === "src") && value.startsWith("javascript:"))) {
        node.removeAttribute(attribute.name);
      }
    });
  });
  return parsed.body.innerHTML;
}

function toast(message, type = "success") {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = message;
  $("#toastRegion").append(item);
  setTimeout(() => item.remove(), 4200);
}

function errorMessage(error) {
  const payload = error.payload;
  if (payload?.detail) return payload.detail;
  if (payload?.message && payload?.errors) {
    return `${payload.message} ${payload.errors.map(item => `${item.field}: ${item.message}`).join("; ")}`;
  }
  return payload?.message || error.message || "Something went wrong.";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.apiKey) headers.set("X-API-Key", state.apiKey);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let payload;
    try { payload = await response.json(); } catch { payload = { detail: response.statusText }; }
    const error = new Error(payload.detail || "Request failed");
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

const viewCopy = {
  overview: ["Workspace", "Good to see you."],
  compose: ["Create", "Compose with AI."],
  contacts: ["Audience", "People you can reach."],
  campaigns: ["Outbox", "Review before sending."],
  settings: ["Configuration", "Make it yours."],
};

function go(view) {
  $$(".view").forEach(item => item.classList.toggle("active", item.id === `view-${view}`));
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view));
  $("#pageEyebrow").textContent = viewCopy[view][0];
  $("#pageTitle").textContent = viewCopy[view][1];
  history.replaceState(null, "", `#${view}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setConnectedUI() {
  const connected = Boolean(state.workspace);
  $("#setupBanner").classList.toggle("hidden", connected);
  $("#keyStatus").textContent = connected ? "Connected" : "Not connected";
  $("#keyStatus").classList.toggle("good", connected);
  $("#workspacePill").textContent = connected ? state.workspace.tenant.name : "No workspace connected";
  if (connected) {
    $("#providerStatus").textContent = state.workspace.provider_connections.length
      ? `${state.workspace.provider_connections.length} configured`
      : "Not configured";
    $("#providerStatus").classList.toggle("good", state.workspace.provider_connections.length > 0);
  }
}

function renderContacts() {
  $("#contactMetric").textContent = state.workspace ? state.contacts.length : "—";
  $("#contactHeading").textContent = `${state.contacts.length} contact${state.contacts.length === 1 ? "" : "s"}`;
  const list = $("#contactList");
  const picker = $("#composerContacts");
  if (!state.contacts.length) {
    list.className = "list-container empty-state compact";
    list.innerHTML = "<p>No contacts saved yet.</p>";
    picker.innerHTML = "<p>Add contacts in the Contacts section first.</p>";
    return;
  }
  list.className = "list-container";
  list.innerHTML = state.contacts.map(contact => `
    <div class="list-row">
      <div><strong>${escapeHtml(contact.first_name || contact.email.split("@")[0])}</strong><small>${escapeHtml(contact.email)}</small></div>
      <small>${escapeHtml(contact.company || "—")}</small>
      <button class="icon-button danger delete-contact" data-id="${escapeHtml(contact.id)}" title="Delete contact">Delete</button>
    </div>`).join("");
  picker.innerHTML = state.contacts.map((contact, index) => `
    <label class="contact-choice">
      <input type="checkbox" name="contact" value="${index}" checked>
      <span>${escapeHtml(contact.first_name || contact.email)} <small>${escapeHtml(contact.email)}</small></span>
    </label>`).join("");
}

function renderConnections() {
  const connections = state.workspace?.provider_connections || [];
  $("#connectionMetric").textContent = state.workspace ? connections.length : "—";
  $("#composerConnection").innerHTML = connections.length
    ? connections.map(item => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} · ${escapeHtml(item.provider)}</option>`).join("")
    : '<option value="">Set up a provider first</option>';
}

function renderCampaigns() {
  $("#campaignMetric").textContent = state.workspace ? state.campaigns.length : "—";
  const markup = state.campaigns.length ? state.campaigns.map(campaign => `
    <div class="list-row">
      <div><strong>${escapeHtml(campaign.name)}</strong><small>${escapeHtml(campaign.subject)}</small></div>
      <span class="campaign-status">${escapeHtml(campaign.status)}</span>
      <div class="row-actions">
        <button class="icon-button preview-campaign" data-id="${escapeHtml(campaign.id)}">Preview</button>
        ${campaign.status === "draft" ? `<button class="icon-button danger delete-campaign" data-id="${escapeHtml(campaign.id)}">Delete</button>` : ""}
      </div>
    </div>`).join("") : "";
  const full = $("#campaignList");
  const recent = $("#recentCampaigns");
  if (!markup) {
    full.className = "list-container empty-state";
    full.innerHTML = "<p>No campaigns yet. Create one with AI Composer.</p>";
    recent.className = "empty-state compact";
    recent.innerHTML = "<span>✦</span><strong>Your drafts will appear here</strong><p>Start with AI Composer to create your first email.</p>";
  } else {
    full.className = "list-container";
    full.innerHTML = markup;
    recent.className = "list-container";
    recent.innerHTML = state.campaigns.slice(0, 3).map(campaign => `
      <div class="list-row">
        <div><strong>${escapeHtml(campaign.name)}</strong><small>${escapeHtml(campaign.subject)}</small></div>
        <span class="campaign-status">${escapeHtml(campaign.status)}</span>
        <button class="icon-button preview-campaign" data-id="${escapeHtml(campaign.id)}">Preview</button>
      </div>`).join("");
  }
}

async function loadWorkspace() {
  if (!state.apiKey) {
    state.workspace = null;
    state.contacts = [];
    state.campaigns = [];
    setConnectedUI(); renderContacts(); renderConnections(); renderCampaigns();
    return;
  }
  try {
    const [workspace, contacts, campaigns] = await Promise.all([
      api("/v1/workspace"), api("/v1/contacts"), api("/v1/campaigns")
    ]);
    state.workspace = workspace;
    state.contacts = contacts.contacts;
    state.campaigns = campaigns.campaigns;
    setConnectedUI(); renderContacts(); renderConnections(); renderCampaigns();
  } catch (error) {
    if (error.status === 401) {
      sessionStorage.removeItem("smartmailer_api_key");
      state.apiKey = "";
      state.workspace = null;
      setConnectedUI();
      toast("That workspace key is invalid or revoked.", "error");
      go("settings");
    } else {
      toast(errorMessage(error), "error");
    }
  }
}

const providerDefinitions = {
  sendgrid: [
    ["api_key", "SendGrid API key", "password"], ["sender_name", "Sender name", "text"], ["sender_email", "Sender email", "email"]
  ],
  smtp: [
    ["host", "SMTP host", "text"], ["port", "Port", "number"], ["username", "Username", "text"],
    ["password", "SMTP/app password", "password"], ["sender_name", "Sender name", "text"], ["sender_email", "Sender email", "email"]
  ],
  office365: [
    ["username", "Microsoft 365 email", "email"], ["password", "App password", "password"],
    ["sender_name", "Sender name", "text"], ["sender_email", "Sender email", "email"]
  ],
  graph: [
    ["tenant_id", "Tenant ID", "text"], ["client_id", "Client ID", "text"], ["client_secret", "Client secret", "password"],
    ["sender_email", "Sender email", "email"]
  ],
};

function renderProviderFields() {
  const provider = $("#providerSelect").value;
  $("#providerFields").innerHTML = providerDefinitions[provider].map(([name, label, type]) => `
    <label>${label}<input name="${name}" type="${type}" ${name === "port" ? 'value="587"' : ""} required autocomplete="off"></label>
  `).join("");
}

async function previewCampaign(id) {
  try {
    const data = await api(`/v1/campaigns/${id}/preview`, { method: "POST", body: JSON.stringify({ contact_index: 0 }) });
    const report = data.deliverability;
    const campaign = state.campaigns.find(item => item.id === id);
    $("#campaignPreview").innerHTML = `
      <p class="eyebrow">Preview · ${escapeHtml(data.contact.email)}</p>
      <h2>${escapeHtml(data.message.subject)}</h2>
      <div class="email-paper"><div class="email-body">${safeEmailHtml(data.message.html_body)}</div></div>
      <div class="score-line"><span>Deliverability risk</span><strong>${report.risk_score}/100 · ${escapeHtml(report.risk_level)}</strong></div>
      <p>${escapeHtml(data.notice)}</p>
      ${campaign?.status === "draft"
        ? `<button class="button primary full send-campaign" data-id="${escapeHtml(id)}">Review complete — send campaign</button>`
        : '<span class="status-chip good">This campaign has already been processed</span>'}`;
    $("#previewDialog").showModal();
  } catch (error) { toast(errorMessage(error), "error"); }
}

document.addEventListener("click", async event => {
  const goButton = event.target.closest("[data-go]");
  if (goButton) go(goButton.dataset.go);
  const navButton = event.target.closest("[data-view]");
  if (navButton) go(navButton.dataset.view);
  if (event.target.closest(".dialog-close") || event.target.closest(".dialog-done")) {
    event.target.closest("dialog").close();
  }
  const deleteContact = event.target.closest(".delete-contact");
  if (deleteContact && confirm("Remove this contact from the workspace?")) {
    try { await api(`/v1/contacts/${deleteContact.dataset.id}`, { method: "DELETE" }); await loadWorkspace(); toast("Contact removed."); }
    catch (error) { toast(errorMessage(error), "error"); }
  }
  const deleteCampaign = event.target.closest(".delete-campaign");
  if (deleteCampaign && confirm("Delete this unsent campaign draft?")) {
    try { await api(`/v1/campaigns/${deleteCampaign.dataset.id}`, { method: "DELETE" }); await loadWorkspace(); toast("Draft deleted."); }
    catch (error) { toast(errorMessage(error), "error"); }
  }
  const preview = event.target.closest(".preview-campaign");
  if (preview) previewCampaign(preview.dataset.id);
  const send = event.target.closest(".send-campaign");
  if (send) {
    if (!confirm("Send this campaign now to every listed recipient? This cannot be undone.")) return;
    send.disabled = true;
    send.textContent = "Sending…";
    try {
      const result = await api(`/v1/campaigns/${send.dataset.id}/send`, { method: "POST", body: JSON.stringify({ confirm_send: true }) });
      $("#previewDialog").close();
      await loadWorkspace();
      toast(`Send finished: ${result.accepted} accepted, ${result.failed} failed.`);
    } catch (error) { toast(errorMessage(error), "error"); send.disabled = false; send.textContent = "Review complete — send campaign"; }
  }
});

$("#existingKeyForm").addEventListener("submit", async event => {
  event.preventDefault();
  state.apiKey = new FormData(event.currentTarget).get("api_key").trim();
  sessionStorage.setItem("smartmailer_api_key", state.apiKey);
  await loadWorkspace();
  if (state.workspace) { toast("Workspace connected."); go("overview"); }
});

$("#tenantForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const result = await api("/v1/tenants", {
      method: "POST",
      body: JSON.stringify({ name: form.get("name").trim(), api_key_label: form.get("api_key_label").trim() })
    });
    state.apiKey = result.api_key;
    sessionStorage.setItem("smartmailer_api_key", result.api_key);
    $("#newApiKey").textContent = result.api_key;
    $("#keyDialog").showModal();
    await loadWorkspace();
  } catch (error) { toast(errorMessage(error), "error"); }
});

$("#copyKey").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("#newApiKey").textContent);
  $("#copyKey").textContent = "Copied";
});

$("#providerSelect").addEventListener("change", renderProviderFields);
$("#providerForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.workspace) { toast("Connect a workspace first.", "error"); return; }
  const form = new FormData(event.currentTarget);
  const provider = form.get("provider");
  const credentials = {};
  providerDefinitions[provider].forEach(([name, , type]) => {
    const value = form.get(name);
    credentials[name] = type === "number" ? Number(value) : value.trim();
  });
  try {
    await api("/v1/provider-connections", {
      method: "PUT",
      body: JSON.stringify({ name: form.get("name").trim(), provider, credentials })
    });
    event.currentTarget.reset();
    $("#providerSelect").value = provider;
    renderProviderFields();
    await loadWorkspace();
    toast("Email provider saved securely.");
  } catch (error) { toast(errorMessage(error), "error"); }
});

$("#contactForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const contact = Object.fromEntries([...form.entries()].filter(([, value]) => value.trim()));
  try {
    await api("/v1/contacts", { method: "POST", body: JSON.stringify({ contacts: [contact] }) });
    event.currentTarget.reset(); await loadWorkspace(); toast("Contact added.");
  } catch (error) { toast(errorMessage(error), "error"); }
});

$("#csvInput").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  try {
    const result = await api("/v1/contacts/import-csv", { method: "POST", body });
    await loadWorkspace();
    toast(`Imported ${result.saved} contacts${result.invalid_rows.length ? `; ${result.invalid_rows.length} rows skipped` : ""}.`);
  } catch (error) { toast(errorMessage(error), "error"); }
  event.target.value = "";
});
$("#refreshContacts").addEventListener("click", loadWorkspace);

$("#signOutButton").addEventListener("click", async () => {
  sessionStorage.removeItem("smartmailer_api_key");
  state.apiKey = "";
  state.workspace = null;
  state.contacts = [];
  state.campaigns = [];
  try { await fetch("/auth/logout", { method: "POST" }); } finally { location.href = "/login"; }
});

$("#composerForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.workspace) { toast("Connect a workspace first.", "error"); go("settings"); return; }
  const form = new FormData(event.currentTarget);
  const selected = $$('input[name="contact"]:checked', $("#composerContacts")).map(input => state.contacts[Number(input.value)]);
  if (!selected.length) { toast("Choose at least one recipient.", "error"); return; }
  const button = $('button[type="submit"]', event.currentTarget);
  button.disabled = true; button.textContent = "Generating…";
  const payload = {
    name: form.get("name").trim(),
    connection_name: form.get("connection_name"),
    campaign_type: form.get("campaign_type"),
    purpose: form.get("purpose").trim(),
    audience: form.get("audience").trim(),
    brand_voice: form.get("brand_voice").trim(),
    call_to_action: form.get("call_to_action").trim(),
    variables: form.get("variables").split(",").map(item => item.trim()).filter(Boolean),
    contacts: selected.map(({ id, created_at, updated_at, ...contact }) => contact),
  };
  try {
    const result = await api("/v1/campaigns/ai-draft", { method: "POST", body: JSON.stringify(payload) });
    const draft = result.ai_draft;
    const report = result.deliverability;
    $("#aiResult").className = "";
    $("#aiResult").innerHTML = `
      <div class="email-paper">
        <div class="email-meta"><small>Subject</small><strong>${escapeHtml(draft.subject)}</strong></div>
        <div class="email-body">${safeEmailHtml(draft.html_body)}</div>
      </div>
      <div class="score-line"><span>Deliverability risk</span><strong>${report.risk_score}/100 · ${escapeHtml(report.risk_level)}</strong></div>
      <button class="button primary full preview-campaign" data-id="${escapeHtml(result.campaign.id)}">Preview with recipient →</button>`;
    await loadWorkspace();
    toast("AI draft created. Nothing has been sent.");
  } catch (error) { toast(errorMessage(error), "error"); }
  finally { button.disabled = false; button.textContent = "✦ Generate draft"; }
});

renderProviderFields();
if (!["127.0.0.1", "localhost"].includes(location.hostname)) {
  $("#developerApiLink").hidden = true;
}
go((location.hash || "#overview").slice(1) in viewCopy ? (location.hash || "#overview").slice(1) : "overview");
loadWorkspace();
