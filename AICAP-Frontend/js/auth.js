/* ============================================================
   auth.js — Authentication & Profile API integration
   POST /api/auth/login · /register · GET /api/me · PUT /api/profile
   ============================================================ */

/**
 * Login — stores JWT and user metadata in localStorage, updates window.state
 */
async function loginUser(email, password) {
  const res = await apiFetch("/api/auth/login", {
    method: "POST",
    body: { email, password },
  });

  if (!res?.access_token) throw new Error("Invalid response from server");

  localStorage.setItem("access_token", res.access_token);
  localStorage.setItem("user_role", res.role);          // e.g. "USER"
  localStorage.setItem("user_name", res.name);
  localStorage.setItem("user_email", res.email);

  if (window.state) {
    window.state.role  = res.role;
    window.state.name  = res.name;
    window.state.email = res.email;
  }

  return res;
}

/**
 * Register — maps frontend role labels to backend RoleEnum values
 */
async function registerUser({ name, email, password, role }) {
  // Map display label → backend enum
  const roleMap = {
    "just for me":    "USER",
    user:             "USER",
    student:          "USER",
    "i coach others": "WELLNESS_COACH",
    coach:            "WELLNESS_COACH",
    wellness_coach:   "WELLNESS_COACH",
    admin:            "ADMIN",
  };
  const backendRole = roleMap[(role || "just for me").toLowerCase()] || "USER";

  return await apiFetch("/api/auth/register", {
    method: "POST",
    body: { name, email, password, role: backendRole },
  });
}

/**
 * Fetch current user profile — GET /api/me
 */
async function fetchUserProfile() {
  const profile = await apiFetch("/api/me", { method: "GET" });

  if (profile && window.state) {
    window.state.userId          = profile.id;
    window.state.name            = profile.name;
    window.state.email           = profile.email;
    window.state.role            = profile.role;
    window.state.phone           = profile.phone;
    window.state.bio             = profile.bio;
    window.state.profilePicture  = profile.profile_picture;
  }

  return profile;
}

/**
 * Update profile fields — PUT /api/profile
 * Only name, phone, bio, profile_picture are accepted by the backend.
 */
async function updateUserProfile(data) {
  const payload = {};
  if (data.name  !== undefined) payload.name            = data.name;
  if (data.phone !== undefined) payload.phone           = data.phone;
  if (data.bio   !== undefined) payload.bio             = data.bio;
  if (data.profilePicture !== undefined) payload.profile_picture = data.profilePicture;

  const updated = await apiFetch("/api/profile", {
    method: "PUT",
    body: payload,
  });

  if (updated && window.state) {
    if (updated.name)  window.state.name  = updated.name;
    if (updated.phone) window.state.phone = updated.phone;
    if (updated.bio)   window.state.bio   = updated.bio;
    localStorage.setItem("user_name", updated.name);
  }

  return updated;
}

/**
 * Redirect to Google OAuth — GET /api/auth/google
 */
function initiateGoogleLogin() {
  window.location.href = `${API_BASE_URL}/api/auth/google`;
}

/**
 * Logout — clear session and return to landing page
 */
function logoutUser() {
  ["access_token", "user_role", "user_name", "user_email"].forEach((k) =>
    localStorage.removeItem(k)
  );
  if (window.state) {
    Object.assign(window.state, {
      role: null, name: null, email: null, userId: null,
    });
  }
  window.location.hash = "#/";
  // hashchange doesn't fire when the hash is already "#/", so re-render directly
  route();
  showToast("Signed out successfully.", "success");
}