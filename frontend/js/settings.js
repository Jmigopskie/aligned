document.getElementById("sidebar-nav").innerHTML = renderSidebarNav("settings");

const settingsError = document.getElementById("settings-error");
const profileRoleBadge = document.getElementById("profile-role-badge");
const profileMemberSince = document.getElementById("profile-member-since");

const profileForm = document.getElementById("profile-form");
const profileNameInput = document.getElementById("profile-name");
const profileEmailInput = document.getElementById("profile-email");
const profileStatus = document.getElementById("profile-status");
const profileSaveBtn = document.getElementById("profile-save-btn");

const passwordForm = document.getElementById("password-form");
const currentPasswordInput = document.getElementById("current-password");
const newPasswordInput = document.getElementById("new-password");
const confirmPasswordInput = document.getElementById("confirm-password");
const passwordStatus = document.getElementById("password-status");
const passwordSaveBtn = document.getElementById("password-save-btn");

const avatarUploadBtn = document.getElementById("avatar-upload-btn");
const avatarRemoveBtn = document.getElementById("avatar-remove-btn");
const avatarFileInput = document.getElementById("avatar-file-input");

const bannerUploadBtn = document.getElementById("banner-upload-btn");
const bannerRemoveBtn = document.getElementById("banner-remove-btn");
const bannerFileInput = document.getElementById("banner-file-input");
const bannerPreview = document.getElementById("banner-preview");

document.getElementById("logout-btn2").addEventListener("click", async () => {
  try {
    await Api.logout();
  } finally {
    clearCachedUser();
    window.location.href = "index.html";
  }
});

function showSettingsError(message) {
  settingsError.textContent = message;
  settingsError.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

profileForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  settingsError.hidden = true;
  profileStatus.textContent = "";

  const full_name = profileNameInput.value.trim();
  const email = profileEmailInput.value.trim();
  if (!full_name || !email) {
    showSettingsError("Full name and email can't be empty.");
    return;
  }

  setButtonLoading(profileSaveBtn, true, "Saving");
  try {
    const data = await Api.updateMe({ full_name, email });
    cacheUser(data.user);
    document.querySelectorAll(".js-user-name").forEach((el) => (el.textContent = data.user.full_name));
    applyAvatar(data.user);
    profileStatus.textContent = "Saved.";
    showToast("Profile updated.");
  } catch (err) {
    showSettingsError(err.message);
  } finally {
    setButtonLoading(profileSaveBtn, false);
  }
});

passwordForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  settingsError.hidden = true;
  passwordStatus.textContent = "";

  const current = currentPasswordInput.value;
  const next = newPasswordInput.value;
  const confirm = confirmPasswordInput.value;

  if (next.length < 8) {
    showSettingsError("New password must be at least 8 characters.");
    return;
  }
  if (next !== confirm) {
    showSettingsError("New password and confirmation don't match.");
    return;
  }

  setButtonLoading(passwordSaveBtn, true, "Updating");
  try {
    await Api.changePassword(current, next);
    passwordForm.reset();
    passwordStatus.textContent = "Updated.";
    showToast("Password updated.");
  } catch (err) {
    showSettingsError(err.message);
  } finally {
    setButtonLoading(passwordSaveBtn, false);
  }
});

avatarUploadBtn.addEventListener("click", () => avatarFileInput.click());

avatarFileInput.addEventListener("change", async () => {
  const file = avatarFileInput.files[0];
  if (!file) return;
  settingsError.hidden = true;

  setButtonLoading(avatarUploadBtn, true, "Uploading");
  try {
    const data = await Api.uploadAvatar(file);
    cacheUser(data.user);
    applyAvatar(data.user);
    avatarRemoveBtn.hidden = !data.user.avatar_url;
    showToast("Profile picture updated.");
  } catch (err) {
    showSettingsError(err.message);
  } finally {
    setButtonLoading(avatarUploadBtn, false);
    avatarFileInput.value = "";
  }
});

avatarRemoveBtn.addEventListener("click", async () => {
  settingsError.hidden = true;
  setButtonLoading(avatarRemoveBtn, true, "Removing");
  try {
    const data = await Api.deleteAvatar();
    cacheUser(data.user);
    applyAvatar(data.user);
    avatarRemoveBtn.hidden = true;
    showToast("Profile picture removed.");
  } catch (err) {
    showSettingsError(err.message);
  } finally {
    setButtonLoading(avatarRemoveBtn, false);
  }
});

function applyBannerPreview(user) {
  if (user.banner_url) {
    bannerPreview.src = user.banner_url;
    bannerPreview.style.display = "block";
  } else {
    bannerPreview.removeAttribute("src");
    bannerPreview.style.display = "none";
  }
  bannerRemoveBtn.hidden = !user.banner_url;
}

bannerUploadBtn.addEventListener("click", () => bannerFileInput.click());

bannerFileInput.addEventListener("change", async () => {
  const file = bannerFileInput.files[0];
  if (!file) return;
  settingsError.hidden = true;

  setButtonLoading(bannerUploadBtn, true, "Uploading");
  try {
    const data = await Api.uploadBanner(file);
    cacheUser(data.user);
    applyBannerPreview(data.user);
    showToast("Dashboard banner updated.");
  } catch (err) {
    showSettingsError(err.message);
  } finally {
    setButtonLoading(bannerUploadBtn, false);
    bannerFileInput.value = "";
  }
});

bannerRemoveBtn.addEventListener("click", async () => {
  settingsError.hidden = true;
  setButtonLoading(bannerRemoveBtn, true, "Removing");
  try {
    const data = await Api.deleteBanner();
    cacheUser(data.user);
    applyBannerPreview(data.user);
    showToast("Dashboard banner removed.");
  } catch (err) {
    showSettingsError(err.message);
  } finally {
    setButtonLoading(bannerRemoveBtn, false);
  }
});

async function init() {
  const user = await requireAuth();
  if (!user) return;
  wireTopbar(user);

  profileNameInput.value = user.full_name || "";
  profileEmailInput.value = user.email || "";
  profileRoleBadge.textContent = user.role ? user.role[0].toUpperCase() + user.role.slice(1) : "Teacher";
  avatarRemoveBtn.hidden = !user.avatar_url;

  document.querySelectorAll(".js-role-action").forEach((el) => {
    el.hidden = el.dataset.role !== user.role;
  });
  applyBannerPreview(user);
  if (user.created_at) {
    const memberSince = new Date(user.created_at).toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
    profileMemberSince.textContent = `Member since ${memberSince}`;
  }
}

init();
