/* ============================================================
   main.js — App state · Hash router · Toast · Auth forms · Nav
   ============================================================ */

/* ---------- Global state ---------- */

window.state = {
  role:   localStorage.getItem("user_role")  || null,
  name:   localStorage.getItem("user_name")  || null,
  email:  localStorage.getItem("user_email") || null,
  userId: null,
};

/* Role definitions — maps backend role values to display config */
const ROLE_CONFIG = {
  USER: {
    label: "User",
    dashPage: "page-user",
    greeting: "Morning starts here.",
    nav: [
      { id: "alarms",   label: "Alarms",   icon: "🔔" },
      { id: "today",    label: "Today",        icon: "📅" },
      { id: "upcoming", label: "Upcoming",     icon: "⏩" },
      { id: "challenges", label: "Challenges", icon: "🧠" },
      { id: "profile",  label: "Profile",      icon: "👤" },
    ],
  },
  WELLNESS_COACH: {
    label: "Wellness Coach",
    dashPage: "page-coach",
    greeting: "Your circle's mornings, at a glance.",
    nav: [
      { id: "overview", label: "Overview",      icon: "📊" },
      { id: "alarms",   label: "Alarm Manager", icon: "🔔" },
      { id: "profile",  label: "Profile",       icon: "👤" },
    ],
  },
  ADMIN: {
    label: "Admin",
    dashPage: "page-admin",
    greeting: "Everything, all at once.",
    nav: [
      { id: "overview", label: "Overview",     icon: "📊" },
      { id: "users",    label: "Manage Users", icon: "👥" },
      { id: "alarms",   label: "All Alarms",   icon: "🔔" },
      { id: "profile",  label: "Profile",      icon: "👤" },
    ],
  },
};

/* Suffix used on duplicated-but-role-scoped elements (profile form
   fields) so USER / WELLNESS_COACH / ADMIN dashboards — which all
   exist in the DOM simultaneously — never share an element id. */
const ROLE_SUFFIX = { USER: "user", WELLNESS_COACH: "coach", ADMIN: "admin" };

/* ---------- Toast ---------- */

function showToast(msg, type = "info") {
  const region = document.getElementById("toastRegion");
  if (!region) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.setAttribute("role", "status");
  toast.setAttribute("aria-live", "polite");

  toast.innerHTML = `
    <span>${msg}</span>
    <button class="toast-dismiss" aria-label="Dismiss" onclick="this.closest('.toast').remove()">✕</button>
  `;
  region.appendChild(toast);

  // Auto-dismiss after 3.5s
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

/* ---------- Auth tab switch ---------- */

function switchAuthTab(which) {
  document.getElementById("tabLoginBtn")?.classList.toggle("active", which === "login");
  document.getElementById("tabSignupBtn")?.classList.toggle("active", which === "signup");
  document.getElementById("loginForm")?.classList.toggle("hidden", which !== "login");
  document.getElementById("signupForm")?.classList.toggle("hidden", which !== "signup");
  hideAuthError("loginError");
  hideAuthError("signupError");
}

function showAuthError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
}

function hideAuthError(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = "";
  el.hidden = true;
}

/* ---------- Password visibility toggle ---------- */

function togglePw(inputId, btn) {
  const el = document.getElementById(inputId);
  if (!el) return;
  const show = el.type === "password";
  el.type = show ? "text" : "password";
  btn.textContent = show ? "Hide" : "Show";
}

/* ---------- Password strength meter ---------- */

function updatePasswordStrength(password) {
  const bars = document.querySelectorAll(".pw-strength span");
  if (!bars.length) return;

  let score = 0;
  if (password.length >= 8)           score++;
  if (/[A-Z]/.test(password))         score++;
  if (/[0-9]/.test(password))         score++;
  if (/[^A-Za-z0-9]/.test(password))  score++;

  const colours = ["", "#DC2626", "#D97706", "#16A34A", "#1DAD97"];
  bars.forEach((bar, i) => {
    bar.style.background = i < score ? colours[score] : "var(--graphite-soft)";
  });
}

/* ---------- Role picker (registration) ---------- */

let _selectedRole = "USER";
const REGISTERABLE_ROLES = [
  { value: "USER",           label: "Just for me",           desc: "Manage personal alarms and reminders." },
  { value: "WELLNESS_COACH", label: "I coach others", desc: "Support users and monitor alarm engagement." },
];

function buildRolePicker() {
  const grid = document.getElementById("roleSelectGrid");
  if (!grid) return;

  grid.innerHTML = REGISTERABLE_ROLES.map(({ value, label, desc }) => `
    <button
      type="button"
      class="choice-card"
      aria-pressed="${value === _selectedRole}"
      data-role="${value}"
      onclick="pickRole('${value}')">
      <span class="choice-check" aria-hidden="true">✓</span>
      <div>
        <div style="font-weight:700;">${label}</div>
        <div class="text-sm text-muted">${desc}</div>
      </div>
    </button>`
  ).join("");
}

function pickRole(value) {
  _selectedRole = value;
  document.querySelectorAll("#roleSelectGrid .choice-card").forEach((el) => {
    el.setAttribute("aria-pressed", el.dataset.role === value ? "true" : "false");
  });
}

/* ---------- Login form handler ---------- */

async function handleLoginSubmit(evt) {
  evt.preventDefault();
  hideAuthError("loginError");

  const email    = document.getElementById("loginEmail")?.value.trim();
  const password = document.getElementById("loginPassword")?.value;
  const btn      = document.getElementById("loginSubmitBtn");

  if (!email || !password) {
    showAuthError("loginError", "Enter your email and password.");
    return;
  }

  btn.disabled = true;
  btn.classList.add("btn-loading");

  try {
    const res = await loginUser(email, password);
    showToast(`Welcome back, ${res.name.split(" ")[0]}!`, "success");
    route(); // let router show the correct dashboard
  } catch (err) {
    showAuthError("loginError", err.message || "That email or password doesn't match.");
  } finally {
    btn.disabled = false;
    btn.classList.remove("btn-loading");
  }
}

/* ---------- Skip for testing (development only) ---------- */

function skipForTesting() {
  // Set up mock user session
  const mockUser = {
    access_token: "mock-token-for-testing",
    role: "USER",
    name: "Test User",
    email: "test@example.com"
  };
  
  localStorage.setItem("access_token", mockUser.access_token);
  localStorage.setItem("user_role", mockUser.role);
  localStorage.setItem("user_name", mockUser.name);
  localStorage.setItem("user_email", mockUser.email);
  
  if (window.state) {
    window.state.role = mockUser.role;
    window.state.name = mockUser.name;
    window.state.email = mockUser.email;
  }
  
  showToast("Skipped for testing", "info");
  route();
}

/* ---------- Register form handler ---------- */

async function handleSignupSubmit(evt) {
  evt.preventDefault();
  hideAuthError("signupError");

  const name     = document.getElementById("signupName")?.value.trim();
  const email    = document.getElementById("signupEmail")?.value.trim();
  const password = document.getElementById("signupPassword")?.value;
  const confirm  = document.getElementById("signupConfirm")?.value;
  const btn      = document.getElementById("signupSubmitBtn");

  if (!name || !email || !password || !confirm) {
    showAuthError("signupError", "Please fill in every field.");
    return;
  }
  if (password !== confirm) {
    showAuthError("signupError", "Passwords do not match.");
    return;
  }

  btn.disabled = true;
  btn.classList.add("btn-loading");

  try {
    await registerUser({ name, email, password, role: _selectedRole });
    showToast("Account created. Let's set your first alarm.", "success");
    await loginUser(email, password);
    route();
  } catch (err) {
    showAuthError("signupError", err.message || "Registration failed.");
  } finally {
    btn.disabled = false;
    btn.classList.remove("btn-loading");
  }
}

/* ---------- Profile form handler ----------
   One profile form is rendered per role dashboard (id="profileForm-<suffix>")
   so a coach or admin can edit their own profile from their own dashboard
   without colliding with the USER dashboard's copy. The suffix travels via
   data-suffix on the <form>. */

async function handleProfileSubmit(evt) {
  evt.preventDefault();
  const suffix = evt.currentTarget.dataset.suffix || "user";
  const btn = document.getElementById(`profileSaveBtn-${suffix}`);

  const data = {
    name:  document.getElementById(`profileName-${suffix}`)?.value.trim(),
    phone: document.getElementById(`profilePhone-${suffix}`)?.value.trim(),
    bio:   document.getElementById(`profileBio-${suffix}`)?.value.trim(),
  };

  if (btn) { btn.disabled = true; btn.classList.add("btn-loading"); }

  try {
    await updateUserProfile(data);
    showToast("Changes saved.", "success");
    _updateTopbar();
  } catch (err) {
    showToast(`Save failed: ${err.message}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove("btn-loading"); }
  }
}

/* ---------- Topbar ---------- */

function _updateTopbar() {
  const name = window.state.name || localStorage.getItem("user_name") || "?";
  const role = window.state.role || localStorage.getItem("user_role") || "";
  const cfg  = ROLE_CONFIG[role] || {};

  const avatar = document.getElementById("topbarAvatar");
  if (avatar) avatar.textContent = name.trim()[0]?.toUpperCase() || "?";

  const nameEl = document.getElementById("topbarName");
  if (nameEl) nameEl.textContent = name;

  const roleEl = document.getElementById("topbarRole");
  if (roleEl) roleEl.textContent = cfg.label || role;
}

/* ---------- Sidebar nav builder ---------- */

function _buildSidebar(role) {
  const cfg = ROLE_CONFIG[role];
  if (!cfg) return;

  const navId = `${role.toLowerCase()}_nav`;
  const nav   = document.getElementById(navId);
  if (!nav) return;

  // Set greeting in the dashboard
  const greetingId = `${role.toLowerCase()}Greeting`;
  const greetingEl = document.getElementById(greetingId);
  if (greetingEl && cfg.greeting) {
    greetingEl.textContent = cfg.greeting;
  }

  nav.innerHTML = `
    <div class="sidebar-title">${cfg.label}</div>
    ${cfg.nav.map(({ id, label, icon }) => `
      <a href="#"
         class="sidebar-link"
         data-view="${id}"
         onclick="showView('${role}','${id}',this);return false;">
        <span aria-hidden="true">${icon}</span>
        ${label}
      </a>`).join("")}`;
}

function showView(role, viewId, linkEl) {
  // Deactivate all views inside this role's page
  const page = document.getElementById(`page-${role.toLowerCase()}`);
  if (!page) return;

  page.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const target = document.getElementById(`${role.toLowerCase()}-${viewId}`);
  if (target) target.classList.add("active");

  // Update sidebar active link
  page.querySelectorAll(".sidebar-link").forEach((l) => l.classList.remove("active"));
  if (linkEl) linkEl.classList.add("active");

  // Load dynamic data for this view
  _loadViewData(role, viewId);
}

async function _loadViewData(role, viewId) {
  const suffix = ROLE_SUFFIX[role] || "user";

  if (role === "USER") {
    if (viewId === "alarms")   await loadAlarmManagerView("alarmsContainer", "nextAlarmBanner");
    if (viewId === "today")    await _loadTodayView();
    if (viewId === "upcoming") await _loadUpcomingView();
    if (viewId === "challenges") await loadChallengeStatsView();
  }

  if (role === "WELLNESS_COACH") {
    if (viewId === "overview") await _loadCoachOverview();
    if (viewId === "alarms")   await loadAlarmManagerView("coachAlarmsContainer", null);
  }

  if (role === "ADMIN") {
    if (viewId === "overview") await _loadAdminOverview();
    if (viewId === "users")    await _loadAdminUsers();
    if (viewId === "alarms")   await loadAdminAlarmsView();
  }

  if (viewId === "profile") await _loadProfileView(suffix);
}

/* ---------- Specific view loaders ---------- */

async function _loadAdminOverview() {
  try {
    const data = await apiFetch("/api/admin/dashboard", { method: "GET" });
    _setText("stat-total-users",  data.stats?.total_users   ?? "—");
    _setText("stat-total-alarms", data.stats?.total_alarms  ?? "—");
    _setText("stat-active-alarms",data.stats?.active_alarms ?? "—");
  } catch (err) {
    console.warn("Admin overview failed:", err.message);
  }
}

async function _loadAdminUsers() {
  const tbody = document.getElementById("adminUsersBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="5" class="text-muted">Loading…</td></tr>`;
  try {
    const users = await apiFetch("/api/admin/users", { method: "GET" });
    tbody.innerHTML = users.map((u) => `
      <tr>
        <td>${_esc(u.name)}</td>
        <td>${_esc(u.email)}</td>
        <td><span class="badge badge-type">${u.role}</span></td>
        <td>${u.alarm_count}</td>
        <td class="text-mono text-xs">${u.created_at.slice(0,10)}</td>
      </tr>`).join("") || `<tr><td colspan="5" class="text-muted">No one's signed in yet. Once people join, they'll show up here.</td></tr>`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-muted">Failed to load users.</td></tr>`;
  }
}

/* Coach overview — real roster stats from GET /api/wellness/dashboard */
async function _loadCoachOverview() {
  try {
    const data = await apiFetch("/api/wellness/dashboard", { method: "GET" });
    _setText("stat-roster-users",   data.roster_stats?.total_users   ?? "—");
    _setText("stat-roster-alarms",  data.roster_stats?.total_alarms  ?? "—");
    _setText("stat-roster-active",  data.roster_stats?.active_alarms ?? "—");
  } catch (err) {
    console.warn("Coach overview failed:", err.message);
  }
}

async function _loadTodayView() {
  const container = document.getElementById("todayAlarmsContainer");
  if (!container) return;
  container.innerHTML = `<div class="skeleton" style="height:var(--space-20);"></div>`;
  try {
    const alarms = await fetchTodayAlarms();
    if (!alarms || alarms.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-illustration" aria-hidden="true">
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
              <circle cx="32" cy="28" r="20" stroke="currentColor" stroke-width="2.5" stroke-dasharray="4 3"/>
              <path d="M32 14v14l8 8" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M20 52 Q32 44 44 52" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <h3>Clear skies today.</h3>
          <p>Nothing's ringing before midnight.</p>
          <button class="btn btn-primary" onclick="openAlarmModal()">Add one anyway</button>
        </div>`;
    } else {
      renderAlarmCards(alarms, "todayAlarmsContainer");
    }
  } catch (err) {
    container.innerHTML = `<div class="callout callout-error">Could not load today's alarms.</div>`;
  }
}

async function _loadUpcomingView() {
  const container = document.getElementById("upcomingAlarmsContainer");
  if (!container) return;
  container.innerHTML = `<div class="skeleton" style="height:var(--space-20);"></div>`;
  try {
    const alarms = await fetchUpcomingAlarms();
    if (!alarms || alarms.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-illustration" aria-hidden="true">
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
              <circle cx="32" cy="28" r="20" stroke="currentColor" stroke-width="2.5" stroke-dasharray="4 3"/>
              <path d="M32 14v14l8 8" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M20 52 Q32 44 44 52" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <h3>All caught up.</h3>
          <p>Nothing scheduled ahead. Enjoy the quiet.</p>
        </div>`;
    } else {
      renderAlarmCards(alarms, "upcomingAlarmsContainer");
    }
  } catch (err) {
    container.innerHTML = `<div class="callout callout-error">Could not load upcoming alarms.</div>`;
  }
}

async function _loadProfileView(suffix = "user") {
  try {
    const profile = await fetchUserProfile();
    const f = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ""; };
    f(`profileName-${suffix}`,  profile.name);
    f(`profileEmail-${suffix}`, profile.email);
    f(`profilePhone-${suffix}`, profile.phone);
    f(`profileBio-${suffix}`,   profile.bio);

    const roleEl = document.getElementById(`profileRoleBadge-${suffix}`);
    if (roleEl) roleEl.textContent = profile.role;
    const provEl = document.getElementById(`profileProviderBadge-${suffix}`);
    if (provEl) provEl.textContent = profile.provider;
  } catch (err) {
    showToast("Could not load profile.", "error");
  }
}

function _setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function _esc(str) {
  return String(str ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
}

/* ---------- Hash router ---------- */

function route() {
  const role = window.state.role || localStorage.getItem("user_role");

  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  const topbar = document.getElementById("topbar");

  if (!role || !localStorage.getItem("access_token")) {
    document.getElementById("page-landing")?.classList.add("active");
    if (topbar) topbar.hidden = true;
    return;
  }

  const cfg = ROLE_CONFIG[role];
  if (!cfg) {
    document.getElementById("page-landing")?.classList.add("active");
    if (topbar) topbar.hidden = true;
    return;
  }

  const page = document.getElementById(cfg.dashPage);
  if (page) page.classList.add("active");
  if (topbar) topbar.hidden = false;

  _updateTopbar();
  _buildSidebar(role);

  // Activate first nav item by default
  const firstLink = document.querySelector(`#${role.toLowerCase()}_nav .sidebar-link`);
  if (firstLink) {
    const firstView = firstLink.dataset.view;
    showView(role, firstView, firstLink);
    firstLink.classList.add("active");
  }
}

window.addEventListener("hashchange", route);

/* ---------- DOMContentLoaded ---------- */

document.addEventListener("DOMContentLoaded", () => {
  // Auth forms
  document.getElementById("loginForm")
    ?.addEventListener("submit", handleLoginSubmit);
  document.getElementById("signupForm")
    ?.addEventListener("submit", handleSignupSubmit);

  // Profile forms — one per role dashboard, matched by class
  document.querySelectorAll(".profile-form")
    .forEach((f) => f.addEventListener("submit", handleProfileSubmit));

  // Alarm modal form
  document.getElementById("alarmModalForm")
    ?.addEventListener("submit", handleAlarmModalSubmit);

  // Password strength meter
  document.getElementById("signupPassword")
    ?.addEventListener("input", (e) => updatePasswordStrength(e.target.value));

  // Auth tab switchers
  document.getElementById("tabLoginBtn")
    ?.addEventListener("click", () => switchAuthTab("login"));
  document.getElementById("tabSignupBtn")
    ?.addEventListener("click", () => switchAuthTab("signup"));

  // Logout
  document.getElementById("logoutBtn")
    ?.addEventListener("click", logoutUser);

  // Build role picker
  buildRolePicker();

  // Initial route
  route();
});
