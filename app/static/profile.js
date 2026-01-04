async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  return data;
}

async function loadProfile() {
  try {
    const me = await api("/api/auth/me");
    const name = [me.first_name, me.last_name].filter(Boolean).join(" ");
    document.getElementById("profileName").textContent = name || me.email;
    document.getElementById("profileEmail").textContent = me.email;
  } catch (e) {
    document.getElementById("profileName").textContent = "Not signed in";
    document.getElementById("profileEmail").textContent = "";
  }
}

document.getElementById("passwordForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const out = document.getElementById("passwordOut");
  out.textContent = "Updating...";
  const old_password = document.getElementById("oldPassword").value;
  const new_password = document.getElementById("newPassword").value;
  const confirm_password = document.getElementById("confirmPassword").value;
  try {
    await api("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password, new_password, confirm_password }),
    });
    out.textContent = "Password updated.";
    ev.target.reset();
  } catch (e) {
    out.textContent = e.message;
  }
});

loadProfile();
