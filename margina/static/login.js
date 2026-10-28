const form = document.querySelector("#login-form");
const button = document.querySelector("#login-button");
const errorMessage = document.querySelector("#login-error");

fetch("/api/v1/auth/me")
  .then((response) => {
    if (response.ok) window.location.replace("/workspace");
  })
  .catch(() => {});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorMessage.textContent = "";
  button.disabled = true;
  button.textContent = "Signing in…";
  try {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: document.querySelector("#email").value,
        password: document.querySelector("#password").value,
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error?.message || "Sign in failed.");
    window.location.assign("/workspace");
  } catch (error) {
    errorMessage.textContent = error.message;
    button.disabled = false;
    button.textContent = "Sign in";
    document.querySelector("#password").focus();
  }
});
