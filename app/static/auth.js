async function postAuth(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) return;
  const text = await res.text();
  let msg = text;
  try {
    const data = JSON.parse(text);
    msg = data.detail || JSON.stringify(data);
  } catch {}
  throw new Error(msg);
}

async function getJson(path) {
  const res = await fetch(path);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  return data;
}

const loginForm = document.getElementById("loginForm");
if (loginForm) {
  loginForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;
    const err = document.getElementById("loginError");
    err.textContent = "";
    try {
      await postAuth("/api/auth/login", { email, password });
      window.location.href = "/";
    } catch (e) {
      err.textContent = e.message;
    }
  });
}

const signupForm = document.getElementById("signupForm");
if (signupForm) {
  signupForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const email = document.getElementById("signupEmail").value.trim();
    const password = document.getElementById("signupPassword").value;
    const home_location = (document.getElementById("signupHome") || {}).value || "";
    const err = document.getElementById("signupError");
    err.textContent = "";
    try {
      await postAuth("/api/auth/signup", { email, password, home_location });
      window.location.href = "/";
    } catch (e) {
      err.textContent = e.message;
    }
  });
}

const signupLocBtn = document.getElementById("btnSignupLocation");
if (signupLocBtn) {
  signupLocBtn.addEventListener("click", async () => {
    const err = document.getElementById("signupError");
    err.textContent = "";
    if (!navigator.geolocation) {
      err.textContent = "Geolocation is not supported.";
      return;
    }
    signupLocBtn.disabled = true;
    signupLocBtn.textContent = "Locating...";
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const params = new URLSearchParams();
          params.set("latitude", String(pos.coords.latitude));
          params.set("longitude", String(pos.coords.longitude));
          params.set("results", "5");
          params.set("stops", "true");
          params.set("addresses", "false");
          params.set("poi", "false");
          const data = await getJson(`/api/public/locations/nearby?${params.toString()}`);
          const items = Array.isArray(data) ? data : data.items || [];
          const stop = items.find((c) => c && c.name) || items[0];
          if (!stop) throw new Error("No nearby stop found.");
          const home = document.getElementById("signupHome");
          if (home) home.value = stop.name || "";
        } catch (e) {
          err.textContent = e.message;
        } finally {
          signupLocBtn.disabled = false;
          signupLocBtn.textContent = "Use my location";
        }
      },
      (e) => {
        err.textContent = e.message;
        signupLocBtn.disabled = false;
        signupLocBtn.textContent = "Use my location";
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });
}
