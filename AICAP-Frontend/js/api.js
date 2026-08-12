/* ============================================================
   api.js — FastAPI HTTP Client
   JWT Bearer injection · 401/403/422 error handling · toast hooks
   ============================================================ */

const API_BASE_URL = window.API_BASE_URL || "http://localhost:8000";

/**
 * Core fetch wrapper.
 * - Attaches Authorization: Bearer <token> from localStorage
 * - Serialises plain objects to JSON automatically
 * - On 401 clears session and redirects to landing
 * - On 422 surfaces Pydantic validation errors as readable strings
 * - Throws an enriched Error so callers can show specific messages
 */
async function apiFetch(endpoint, options = {}) {
  const url = endpoint.startsWith("http")
    ? endpoint
    : `${API_BASE_URL}${endpoint}`;

  const headers = { Accept: "application/json", ...options.headers };

  const token = localStorage.getItem("access_token");
  if (token) headers["Authorization"] = `Bearer ${token}`;

  if (
    options.body &&
    typeof options.body === "object" &&
    !(options.body instanceof FormData)
  ) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (networkErr) {
    throw new Error("Lost connection. Retrying…");
  }

  // Session expired or invalid token
  if (response.status === 401) {
    _clearSession();
    if (window.location.hash && window.location.hash !== "#/") {
      window.location.hash = "#/";
      showToast("Session expired. Please sign in again.", "error");
    }
  }

  // Parse JSON body (may be null for 204 No Content)
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    let msg = "An unexpected error occurred.";
    if (data?.detail) {
      if (Array.isArray(data.detail)) {
        // Pydantic 422 — array of {loc, msg, type}
        msg = data.detail
          .map((e) => `${e.loc ? e.loc.slice(-1)[0] : "field"}: ${e.msg}`)
          .join(" · ");
      } else {
        msg = data.detail;
      }
    }
    const err = new Error(msg);
    err.status = response.status;
    err.data = data;
    throw err;
  }

  return data;
}

function _clearSession() {
  ["access_token", "user_role", "user_name", "user_email"].forEach((k) =>
    localStorage.removeItem(k)
  );
  if (window.state) {
    window.state.role = null;
    window.state.name = null;
    window.state.email = null;
    window.state.userId = null;
  }
}