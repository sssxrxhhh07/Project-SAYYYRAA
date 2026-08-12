/* ============================================================
   alarms.js — Module 3 Alarm Management
   CRUD · enable/disable toggle · card renderer · modal controller
   All endpoints match AICAP-Backend/routers/alarm_routes.py
   ============================================================ */

/* ---------- API wrappers ---------- */

const fetchAlarms        = () => apiFetch("/alarms",           { method: "GET"  });
const fetchTodayAlarms   = () => apiFetch("/alarms/today",     { method: "GET"  });
const fetchUpcomingAlarms= () => apiFetch("/alarms/upcoming",  { method: "GET"  });
const checkNextAlarm     = () => apiFetch("/alarms/check-next",{ method: "POST" });
const getAlarm       = (id) => apiFetch(`/alarms/${id}`,   { method: "GET"  });
const deleteAlarm    = (id) => apiFetch(`/alarms/${id}`,   { method: "DELETE"});
const enableAlarm    = (id) => apiFetch(`/alarms/${id}/enable`, { method: "PATCH" });
const disableAlarm   = (id) => apiFetch(`/alarms/${id}/disable`,{ method: "PATCH" });
const snoozeAlarmBackend = (id, minutes = 5) => apiFetch(`/alarms/${id}/snooze`, { method: "PATCH", body: { snooze_minutes: minutes } });
const dismissAlarmBackend = (id, secondsToDismiss = 0) => apiFetch(`/alarms/${id}/dismiss`, { method: "POST", body: { seconds_to_dismiss: secondsToDismiss } });

async function createAlarm(data) {
  return apiFetch("/alarms", { method: "POST", body: _buildPayload(data) });
}

async function updateAlarm(id, data) {
  return apiFetch(`/alarms/${id}`, { method: "PUT", body: _buildPayload(data) });
}

/** Normalise form data → backend-compatible payload */
function _buildPayload(data) {
  const payload = {
    title:            data.title,
    alarm_time:       data.alarm_time,
    alarm_type:       data.alarm_type  || "DAILY",
    difficulty_level: data.difficulty_level || "EASY",
    sound:            data.sound || "default",
    vibration:        data.vibration !== false,
    is_active:        data.is_active !== false,
  };
  if (data.repeat_days && data.repeat_days.length > 0) {
    payload.repeat_days = data.repeat_days.map((d) => d.toUpperCase());
  }
  return payload;
}

/* ---------- Which alarm list is currently on screen ----------
   USER and WELLNESS_COACH each get their own "My Alarms" manager,
   rendered into different container/banner ids so the two role
   dashboards (which both exist in the DOM at once) never fight
   over the same element id. Every refresh call below re-targets
   whichever pair was last opened. */

let _activeAlarmsContainerId = "alarmsContainer";
let _activeBannerId = "nextAlarmBanner";

/* ---------- Toggle handler (called by card checkboxes) ---------- */

async function handleAlarmToggle(alarmId, shouldEnable) {
  try {
    shouldEnable ? await enableAlarm(alarmId) : await disableAlarm(alarmId);
    showToast(`Alarm ${shouldEnable ? "on" : "off"}.`, "success");
    await loadAlarmManagerView(_activeAlarmsContainerId, _activeBannerId);
  } catch (err) {
    showToast(`Could not update alarm: ${err.message}`, "error");
  }
}

/* ---------- Delete handler ---------- */

async function handleAlarmDelete(alarmId, title) {
  if (!confirm(`This alarm's gone for good — delete it?`)) return;
  try {
    await deleteAlarm(alarmId);
    showToast("Alarm deleted.", "success");
    await loadAlarmManagerView(_activeAlarmsContainerId, _activeBannerId);
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "error");
  }
}

/* ---------- Edit — pre-fill modal ---------- */

async function handleAlarmEdit(alarmId) {
  try {
    const alarm = await getAlarm(alarmId);
    _fillModal(alarm);
    openAlarmModal(alarmId);
  } catch (err) {
    showToast(`Could not load alarm: ${err.message}`, "error");
  }
}

function _fillModal(alarm) {
  const f = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val ?? "";
  };
  f("alarmTitleInput",      alarm.title);
  f("alarmTimeInput",       alarm.alarm_time);
  f("alarmTypeInput",       alarm.alarm_type);
  f("alarmDifficultyInput", alarm.difficulty_level);
  f("alarmSoundInput",      alarm.sound);

  // Reset day pills then tick the saved ones
  document.querySelectorAll(".day-pill").forEach((btn) => {
    btn.setAttribute("aria-pressed", "false");
  });
  if (alarm.repeat_days) {
    alarm.repeat_days.forEach((day) => {
      const btn = document.querySelector(`.day-pill[data-day="${day}"]`);
      if (btn) btn.setAttribute("aria-pressed", "true");
    });
  }
}

/* ---------- Load alarm manager view ----------
   containerId/bannerId let the same manager UI be reused for both
   the USER "My Alarms" screen and the WELLNESS_COACH "Alarm Manager"
   screen without id collisions. Pass bannerId = null to skip the
   next-alarm banner entirely (used on the coach dashboard). */

async function loadAlarmManagerView(containerId = "alarmsContainer", bannerId = "nextAlarmBanner") {
  _activeAlarmsContainerId = containerId;
  _activeBannerId = bannerId;

  const container = document.getElementById(containerId);
  if (!container) return;

  // Skeleton while loading
  container.innerHTML = `
    <div class="skeleton" style="height:var(--space-24);"></div>
    <div class="skeleton" style="height:var(--space-24);"></div>
  `;

  try {
    const [alarms, nextResult] = await Promise.all([
      fetchAlarms(),
      bannerId ? checkNextAlarm().catch(() => null) : Promise.resolve(null),
    ]);

    renderAlarmCards(alarms, containerId);
    if (bannerId) renderNextAlarmBanner(nextResult, bannerId);
  } catch (err) {
    container.innerHTML = `
      <div class="callout callout-error">
        <span>⚠</span>
        <span>Could not load alarms: ${err.message}</span>
      </div>`;
  }
}

/* ---------- Refresh every alarm list currently on screen ----------
   Snooze/dismiss mutate the alarm server-side from the ringing
   overlay, which can sit on top of any dashboard view, so refresh
   whichever lists that dashboard actually renders. */

async function refreshAlarmViews() {
  const jobs = [loadAlarmManagerView(_activeAlarmsContainerId, _activeBannerId)];
  if (document.getElementById("todayAlarmsContainer")?.closest(".view")?.classList.contains("active")) {
    jobs.push(_loadTodayView());
  }
  if (document.getElementById("upcomingAlarmsContainer")?.closest(".view")?.classList.contains("active")) {
    jobs.push(_loadUpcomingView());
  }
  await Promise.allSettled(jobs);
}

/* ---------- Render next-alarm banner ---------- */

function renderNextAlarmBanner(nextResult, bannerId = "nextAlarmBanner") {
  const banner = document.getElementById(bannerId);
  if (!banner) return;

  if (nextResult?.alarm) {
    const mins = Math.round(nextResult.time_remaining_seconds / 60);
    banner.innerHTML = `
      <div>
        <div class="eyebrow">Next scheduled alarm</div>
        <div style="font-family:var(--font-mono);font-size:var(--text-xl);font-weight:700;">
          ${nextResult.alarm.alarm_time} — ${nextResult.alarm.title}
        </div>
      </div>
      <span class="badge badge-active" style="font-size:var(--text-sm);">
        Fires in ~${mins} min${mins !== 1 ? "s" : ""}
      </span>`;
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

/* ---------- Alarm card renderer ---------- */

function renderAlarmCards(alarms, containerId = "alarmsContainer") {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!alarms || alarms.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="grid-column:1/-1;">
        <div class="empty-state-illustration" aria-hidden="true">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
            <circle cx="32" cy="28" r="20" stroke="currentColor" stroke-width="2.5" stroke-dasharray="4 3"/>
            <path d="M32 14v14l8 8" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M20 52 Q32 44 44 52" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </div>
        <h3>A blank page.</h3>
        <p>Nothing's set yet — your mornings are wide open.</p>
        <button class="btn btn-primary" onclick="openAlarmModal()">
          Sketch your first alarm
        </button>
      </div>`;
    return;
  }

  container.innerHTML = alarms.map((a) => _alarmCardHTML(a)).join("");
}

function _alarmCardHTML(a) {
  const isActive   = a.is_active;
  const typeLabel  = a.alarm_type.replace("_", " ");
  const diffClass  = { EASY: "badge-easy", MEDIUM: "badge-medium", HARD: "badge-hard" }[a.difficulty_level] || "badge-easy";
  const daysLabel  = a.repeat_days?.length
    ? a.repeat_days.join(" · ")
    : a.alarm_type === "DAILY" ? "Every day" : "One-time";

  // Show adaptive time for SMART_ADAPTIVE alarms
  let displayTime = a.alarm_time;
  let adaptiveInfo = "";
  if (a.alarm_type === "SMART_ADAPTIVE") {
    if (a.adaptive_offset !== 0) {
      const offsetSign = a.adaptive_offset > 0 ? "+" : "";
      displayTime = `${a.alarm_time} <span class="text-xs text-muted">(${offsetSign}${a.adaptive_offset}min)</span>`;
      adaptiveInfo = `<div class="text-xs text-muted" style="margin-top:var(--space-1);">
        🧠 Nudged ${offsetSign}${a.adaptive_offset}min — based on your last few mornings.
      </div>`;
    } else {
      adaptiveInfo = `<div class="text-xs text-muted" style="margin-top:var(--space-1);">
        🧠 Still learning. Give it a few mornings and it'll start adjusting on its own.
      </div>`;
    }
  }

  return `
<div class="alarm-card${isActive ? "" : " is-inactive"}" id="alarm-card-${a.id}">
  <div class="alarm-card-time">${displayTime}</div>

  <div class="alarm-card-info">
    <div class="alarm-card-title">${_esc(a.title)}</div>
    <div class="alarm-card-meta">
      <span class="badge badge-type">${typeLabel}</span>
      <span class="badge ${diffClass}">${a.difficulty_level}</span>
      <span class="alarm-card-days text-mono">${daysLabel}</span>
    </div>
    <div class="text-sm text-muted" style="margin-top:var(--space-1);">
      🔊 ${_esc(a.sound || "default")}
      ${a.vibration ? " · 📳 vibration" : ""}
    </div>
    ${adaptiveInfo}
  </div>

  <div class="alarm-card-actions">
    <button
      class="toggle"
      role="switch"
      aria-checked="${isActive}"
      aria-label="${isActive ? "Disable" : "Enable"} alarm"
      onclick="handleAlarmToggle(${a.id}, !(this.getAttribute('aria-checked')==='true'))">
      <span class="toggle-knob"></span>
    </button>
    <button class="btn btn-sm btn-secondary" onclick="handleAlarmEdit(${a.id})" aria-label="Edit alarm">
      Edit
    </button>
    <button class="btn btn-sm btn-destructive" onclick="handleAlarmDelete(${a.id}, '${_esc(a.title)}')" aria-label="Delete alarm">
      Delete
    </button>
  </div>
</div>`;
}

function _esc(str) {
  return String(str ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
}

/* ---------- Admin — all-alarms read-only table ----------
   Admin sees every user's alarms via GET /api/admin/alarms. That
   payload doesn't include repeat_days/sound/vibration and the
   per-user CRUD endpoints reject actions on alarms you don't own,
   so this renders a read-only table instead of reusing the
   interactive alarm-card component. */

async function loadAdminAlarmsView() {
  const tbody = document.getElementById("adminAlarmsBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="text-muted">Loading…</td></tr>`;
  try {
    const alarms = await apiFetch("/api/admin/alarms", { method: "GET" });
    tbody.innerHTML = alarms.map((a) => `
      <tr>
        <td>${_esc(a.title)}</td>
        <td class="text-mono">${a.alarm_time}</td>
        <td><span class="badge badge-type">${a.alarm_type.replace("_"," ")}</span></td>
        <td><span class="badge ${a.is_active ? "badge-active" : "badge-inactive"}">${a.is_active ? "Active" : "Inactive"}</span></td>
        <td>${_esc(a.user_name)}</td>
        <td class="text-mono text-xs">${a.created_at.slice(0,10)}</td>
      </tr>`).join("") || `<tr><td colspan="6" class="text-muted">No alarms yet.</td></tr>`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted">Failed to load alarms.</td></tr>`;
  }
}

/* ---------- Create / Edit modal controller ---------- */

let _editingAlarmId = null;

function openAlarmModal(editId = null) {
  _editingAlarmId = editId || null;
  const modal  = document.getElementById("alarmModal");
  const title  = document.getElementById("alarmModalTitle");
  const submit = document.getElementById("alarmModalSubmit");
  if (!modal) return;

  if (!editId) {
    document.getElementById("alarmModalForm")?.reset();
    document.querySelectorAll(".day-pill").forEach((b) => b.setAttribute("aria-pressed","false"));
  }

  if (title)  title.textContent  = editId ? "Edit alarm"  : "New alarm";
  if (submit) submit.textContent = editId ? "Save changes" : "Create alarm";

  modal.hidden = false;
  modal.removeAttribute("aria-hidden");
  document.getElementById("alarmTitleInput")?.focus();
}

function closeAlarmModal() {
  const modal = document.getElementById("alarmModal");
  if (!modal) return;
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
  _editingAlarmId = null;
}

async function handleAlarmModalSubmit(evt) {
  evt.preventDefault();
  const btn = document.getElementById("alarmModalSubmit");

  const title      = document.getElementById("alarmTitleInput")?.value.trim();
  const alarm_time = document.getElementById("alarmTimeInput")?.value;
  const alarm_type = document.getElementById("alarmTypeInput")?.value;
  const difficulty_level = document.getElementById("alarmDifficultyInput")?.value;
  const sound      = document.getElementById("alarmSoundInput")?.value || "default";

  const repeat_days = Array.from(
    document.querySelectorAll('.day-pill[aria-pressed="true"]')
  ).map((b) => b.dataset.day);

  if (!title || !alarm_time) {
    showToast("Title and time are required.", "error");
    return;
  }

  if (btn) { btn.disabled = true; btn.classList.add("btn-loading"); }

  try {
    if (_editingAlarmId) {
      await updateAlarm(_editingAlarmId, { title, alarm_time, alarm_type, difficulty_level, sound, repeat_days });
      showToast("Alarm saved.", "success");
    } else {
      await createAlarm({ title, alarm_time, alarm_type, difficulty_level, sound, repeat_days });
      showToast("Alarm saved.", "success");
    }
    closeAlarmModal();
    await loadAlarmManagerView(_activeAlarmsContainerId, _activeBannerId);
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove("btn-loading"); }
  }
}

/* ---------- Day-pill toggle (used inline from HTML) ---------- */

function toggleDayPill(btn) {
  const pressed = btn.getAttribute("aria-pressed") === "true";
  btn.setAttribute("aria-pressed", String(!pressed));
}
