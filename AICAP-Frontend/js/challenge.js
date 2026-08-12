/* ============================================================
   challenge.js — Module 4 Cognitive Challenge System
   Renders the challenge that gates alarm dismissal, submits
   answers, and reflects the server's verdict.
   All endpoints match AICAP-Backend/routers/challenge_routes.py
   ============================================================ */

const CognitiveChallenge = {
  attempt: null,
  alarmId: null,
  countdownId: null,
  submitting: false,

  /* ---------- Lifecycle ---------- */

  /** Fetch and render a challenge for a ringing alarm. */
  async start(alarmId) {
    this.reset();
    this.alarmId = alarmId;

    const panel = document.getElementById("challengePanel");
    const body = document.getElementById("challengeBody");
    if (!panel || !body) return;

    panel.hidden = false;
    body.innerHTML = `<div class="skeleton" style="height:var(--space-16);"></div>`;
    this._setFallbackVisible(false);

    try {
      this.attempt = await apiFetch("/challenges/start", {
        method: "POST",
        body: { alarm_id: alarmId },
      });
      this._render();
    } catch (err) {
      // Never trap the user behind a broken challenge — fall back to dismiss.
      body.innerHTML = `<div class="callout callout-error">
        <span>⚠</span><span>Couldn't load a challenge: ${_esc(err.message)}</span>
      </div>`;
      this._setFallbackVisible(true);
    }
  },

  /** Clear challenge state and UI (called when the overlay closes). */
  reset() {
    this.attempt = null;
    this.alarmId = null;
    this.submitting = false;
    if (this.countdownId) {
      clearInterval(this.countdownId);
      this.countdownId = null;
    }
    const panel = document.getElementById("challengePanel");
    if (panel) panel.hidden = true;
  },

  /* ---------- Rendering ---------- */

  _render() {
    const a = this.attempt;
    const body = document.getElementById("challengeBody");
    if (!body || !a) return;

    const meta = a.metadata || {};
    const attemptsLabel = a.max_attempts > 1
      ? `${a.max_attempts} attempts allowed`
      : "one attempt only";

    body.innerHTML = `
      <div class="stack gap-3" style="text-align:left;">
        <div class="row-flex gap-2" style="justify-content:space-between;align-items:center;">
          <span class="badge badge-type">${a.challenge_type.replace(/_/g, " ")}</span>
          <span class="badge ${_difficultyBadgeClass(a.difficulty)}">${a.difficulty}</span>
          <span class="text-mono text-sm" id="challengeTimer" aria-live="off"></span>
        </div>

        <p id="challengePrompt" style="white-space:pre-line;font-weight:600;">${_esc(a.prompt)}</p>
        <div id="challengeSequence" class="text-mono" style="font-size:var(--text-xl);letter-spacing:0.1em;"></div>
        <div id="challengeInputArea"></div>

        <p class="text-sm text-muted" id="challengeFeedback" role="status" aria-live="polite">${attemptsLabel}.</p>
      </div>`;

    if (a.answer_format === "sequence" && Array.isArray(meta.sequence)) {
      this._renderMemorySequence(meta);
    } else {
      this._renderInput();
    }

    this._startCountdown();
  },

  /** MEMORY: flash the sequence, then hide it and ask for it back. */
  _renderMemorySequence(meta) {
    const holder = document.getElementById("challengeSequence");
    const seconds = meta.display_seconds || 5;
    if (!holder) return;

    holder.textContent = meta.sequence.join(" · ");
    setTimeout(() => {
      holder.textContent = "— hidden —";
      this._renderInput();
    }, seconds * 1000);
  },

  _renderInput() {
    const a = this.attempt;
    const area = document.getElementById("challengeInputArea");
    if (!area || !a) return;

    if (a.answer_format === "mcq" && Array.isArray(a.options)) {
      area.innerHTML = `
        <div class="stack gap-2">
          ${a.options.map((opt) => `
            <button type="button" class="btn btn-secondary" data-answer="${_esc(opt)}"
                    onclick="CognitiveChallenge.submit(this.dataset.answer)">
              ${_esc(opt)}
            </button>`).join("")}
        </div>`;
      return;
    }

    const inputType = a.answer_format === "number" ? "text" : "text";
    const placeholder = {
      number: "Your answer (a number)",
      sequence: "e.g. 4-7-2",
      text: "Your answer",
    }[a.answer_format] || "Your answer";

    area.innerHTML = `
      <form class="row-flex gap-2" onsubmit="CognitiveChallenge.submitFromForm(event)">
        <input class="input" type="${inputType}" id="challengeAnswerInput"
               placeholder="${placeholder}" autocomplete="off" maxlength="500">
        <button type="submit" class="btn btn-primary" id="challengeSubmitBtn">Submit</button>
      </form>`;
    document.getElementById("challengeAnswerInput")?.focus();
  },

  /** Client-side countdown is UX only — the server enforces the real limit. */
  _startCountdown() {
    const el = document.getElementById("challengeTimer");
    if (!el || !this.attempt) return;

    let remaining = this.attempt.seconds_remaining;
    const tick = () => {
      el.textContent = `${Math.max(0, remaining)}s left`;
      if (remaining <= 0) {
        clearInterval(this.countdownId);
        this.countdownId = null;
        this.submit("");  // let the server record the timeout
        return;
      }
      remaining -= 1;
    };

    tick();
    this.countdownId = setInterval(tick, 1000);
  },

  /* ---------- Submission ---------- */

  submitFromForm(evt) {
    evt.preventDefault();
    this.submit(document.getElementById("challengeAnswerInput")?.value || "");
  },

  async submit(answer) {
    if (!this.attempt || this.submitting) return;
    this.submitting = true;

    const feedback = document.getElementById("challengeFeedback");
    try {
      const result = await apiFetch(`/challenges/${this.attempt.attempt_id}/submit`, {
        method: "POST",
        body: { answer: String(answer ?? "") },
      });
      await this._applyResult(result);
    } catch (err) {
      if (feedback) feedback.textContent = `Couldn't check that: ${err.message}`;
      this._setFallbackVisible(true);
    } finally {
      this.submitting = false;
    }
  },

  async _applyResult(result) {
    const feedback = document.getElementById("challengeFeedback");

    if (result.is_correct) {
      if (this.countdownId) {
        clearInterval(this.countdownId);
        this.countdownId = null;
      }
      showToast(`Solved — +${result.score} points.`, "success");
      // The server already recorded the dismissal, so just stand the alarm down.
      await AlarmAudio.handleAlarmAction(this.alarmId, "challenge-passed");
      return;
    }

    if (result.status === "IN_PROGRESS") {
      this.attempt.attempts_used = result.attempts_used;
      if (feedback) feedback.textContent = result.message;
      const input = document.getElementById("challengeAnswerInput");
      if (input) { input.value = ""; input.focus(); }
      return;
    }

    if (feedback) feedback.textContent = `${result.message} A new one is on the way.`;
    this._setFallbackVisible(result.fallback_available);

    if (result.fallback_available) {
      if (this.countdownId) {
        clearInterval(this.countdownId);
        this.countdownId = null;
      }
      return;
    }

    // Escalation path: hand out a fresh challenge so the alarm stays beatable.
    await this.start(this.alarmId);
  },

  /** Reveal the manual "I'm up" escape hatch. */
  _setFallbackVisible(visible) {
    const btn = document.getElementById("alarmDismissBtn");
    const note = document.getElementById("challengeFallbackNote");
    if (btn) btn.hidden = !visible;
    if (note) note.hidden = !visible;
  },
};

function _difficultyBadgeClass(difficulty) {
  return { EASY: "badge-easy", MEDIUM: "badge-medium", HARD: "badge-hard" }[difficulty] || "badge-easy";
}

/* ---------- Challenge stats (dashboard widget) ---------- */

async function loadChallengeStatsView() {
  const container = document.getElementById("challengeStatsContainer");
  if (!container) return;

  container.innerHTML = `<div class="skeleton" style="height:var(--space-16);"></div>`;
  try {
    const stats = await apiFetch("/challenges/stats", { method: "GET" });
    const pct = (value) => (value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`);
    const secs = (value) => (value === null || value === undefined ? "—" : `${Math.round(value)}s`);

    container.innerHTML = `
      <div class="grid-3">
        ${_statCard("Challenges solved", `${stats.completed}/${stats.total_attempts}`)}
        ${_statCard("Accuracy", pct(stats.accuracy))}
        ${_statCard("Average solve time", secs(stats.average_time_seconds))}
        ${_statCard("Current level", stats.current_difficulty)}
        ${_statCard("Streak", `${stats.current_streak}`)}
        ${_statCard("Total score", `${stats.total_score}`)}
      </div>
      ${stats.per_type.length ? `
        <table class="data-table" style="margin-top:var(--space-6);">
          <thead><tr><th>Type</th><th>Attempts</th><th>Accuracy</th><th>Avg time</th></tr></thead>
          <tbody>
            ${stats.per_type.map((row) => `
              <tr>
                <td>${row.challenge_type.replace(/_/g, " ")}</td>
                <td>${row.attempts}</td>
                <td>${pct(row.accuracy)}</td>
                <td>${secs(row.average_time_seconds)}</td>
              </tr>`).join("")}
          </tbody>
        </table>` : ""}`;
  } catch (err) {
    container.innerHTML = `<div class="callout callout-error">Could not load challenge stats.</div>`;
  }
}

function _statCard(label, value) {
  return `
    <div class="stat-card">
      <span class="stat-card-label">${label}</span>
      <span class="stat-card-value">${_esc(value)}</span>
    </div>`;
}
