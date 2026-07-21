const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let refreshTimer = null;
let cameraStream = null;
let cameraScanLoop = null;

// ---------------- View management ----------------
function showView(id) {
  $$('.view').forEach(v => v.classList.add('hidden'));
  $(id).classList.remove('hidden');
}

async function boot() {
  const res = await fetch('/api/status');
  const data = await res.json();
  const versionEl = $('#app-version');
  if (versionEl && data.version) versionEl.textContent = `v${data.version}`;
  if (!data.initialized) {
    showView('#view-setup');
  } else if (!data.unlocked) {
    showView('#view-lock');
  } else {
    showView('#view-dashboard');
    startDashboard();
  }
  checkForUpdate();
}

// ---------------- Auto-update ----------------
let updatePollTimer = null;

async function checkForUpdate() {
  await fetch('/api/update/check', { method: 'POST' });
  updatePollTimer = setInterval(pollUpdateStatus, 1500);
}

async function pollUpdateStatus() {
  let data;
  try {
    const res = await fetch('/api/update/status');
    data = await res.json();
  } catch (e) {
    return; // server likely mid-restart after an applied update
  }
  renderUpdateBanner(data);
  if (data.phase === 'error') clearInterval(updatePollTimer);
}

function renderUpdateBanner(data) {
  const banner = $('#update-banner');
  const text = $('#update-banner-text');
  const btn = $('#update-banner-btn');

  if (data.phase === 'available') {
    text.textContent = `Version ${data.latest_version} is available.`;
    btn.textContent = 'Update';
    btn.disabled = false;
    banner.classList.remove('hidden');
  } else if (data.phase === 'downloading') {
    text.textContent = `Downloading update… ${data.percent || 0}%`;
    btn.disabled = true;
    banner.classList.remove('hidden');
  } else if (data.phase === 'verifying') {
    text.textContent = 'Verifying update…';
    btn.disabled = true;
    banner.classList.remove('hidden');
  } else if (data.phase === 'applying') {
    text.textContent = 'Restarting with the new version…';
    btn.disabled = true;
    banner.classList.remove('hidden');
  } else if (data.phase === 'error') {
    text.textContent = `Update failed: ${data.error}`;
    btn.textContent = 'Retry';
    btn.disabled = false;
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }
}

$('#update-banner-btn').addEventListener('click', async () => {
  await fetch('/api/update/apply', { method: 'POST' });
});

// ---------------- Setup ----------------
$('#setup-submit').addEventListener('click', async () => {
  const pw = $('#setup-password').value;
  const pw2 = $('#setup-password-confirm').value;
  const errEl = $('#setup-error');
  errEl.textContent = '';

  if (pw.length < 6) { errEl.textContent = 'Use at least 6 characters.'; return; }
  if (pw !== pw2) { errEl.textContent = "Passwords don't match."; return; }

  const res = await fetch('/api/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pw })
  });
  const data = await res.json();
  if (data.error) { errEl.textContent = data.error; return; }
  showView('#view-dashboard');
  startDashboard();
});

// ---------------- Lock / Unlock ----------------
$('#lock-submit').addEventListener('click', unlock);
$('#lock-password').addEventListener('keydown', (e) => { if (e.key === 'Enter') unlock(); });

async function unlock() {
  const pw = $('#lock-password').value;
  const errEl = $('#lock-error');
  errEl.textContent = '';

  const res = await fetch('/api/unlock', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pw })
  });
  const data = await res.json();
  if (data.error) { errEl.textContent = data.error; return; }
  $('#lock-password').value = '';
  showView('#view-dashboard');
  startDashboard();
}

$('#btn-lock').addEventListener('click', async () => {
  await fetch('/api/lock', { method: 'POST' });
  clearInterval(refreshTimer);
  if (tickLoopHandle) { cancelAnimationFrame(tickLoopHandle); tickLoopHandle = null; }
  cardRegistry.clear();
  $('#account-grid').innerHTML = '';
  showView('#view-lock');
});

// ---------------- Dashboard ----------------
function startDashboard() {
  refreshAccounts();
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshAccounts, 1000);
}

async function refreshAccounts() {
  const res = await fetch('/api/accounts');
  if (res.status === 401) { showView('#view-lock'); clearInterval(refreshTimer); return; }
  const data = await res.json();
  renderAccounts(data.accounts || []);
}

// accountId -> { el, data, dialCircle, codeEl, lastCode }
const cardRegistry = new Map();
let tickLoopHandle = null;

function renderAccounts(accounts) {
  const list = $('#account-grid');
  const empty = $('#empty-state');

  if (accounts.length === 0) {
    list.innerHTML = '';
    cardRegistry.clear();
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  const seenIds = new Set();

  accounts.forEach((acct, i) => {
    seenIds.add(acct.id);
    if (!cardRegistry.has(acct.id)) {
      // First time we've seen this account: build its DOM once.
      const el = buildRow(acct, i);
      list.appendChild(el);
      cardRegistry.set(acct.id, {
        el,
        data: acct,
        dialCircle: el.querySelector('.dial-progress'),
        codeEl: el.querySelector('.code-value'),
        lastCode: null,
      });
    }
    const entry = cardRegistry.get(acct.id);
    entry.data = acct; // keep latest server data (secret-free) for click handlers
    updateRowCode(entry, acct);
  });

  // Remove rows for accounts that no longer exist (deleted elsewhere)
  for (const [id, entry] of cardRegistry) {
    if (!seenIds.has(id)) {
      entry.el.remove();
      cardRegistry.delete(id);
    }
  }

  if (!tickLoopHandle) startTickLoop();
}

function updateRowCode(entry, acct) {
  if (acct.code !== entry.lastCode) {
    entry.lastCode = acct.code;
    entry.codeEl.innerHTML = digitCellsHTML(acct.code);
    entry.el.classList.remove('just-updated');
    // force reflow so the animation can retrigger
    void entry.el.offsetWidth;
    entry.el.classList.add('just-updated');
  }
}

// A single rAF loop drives every dial's countdown locally, based on wall-clock
// time, so the ring animates smoothly instead of jumping once per network poll.
function startTickLoop() {
  function tick() {
    const now = Date.now() / 1000;
    for (const entry of cardRegistry.values()) {
      if (entry.data.type !== 'totp' || !entry.dialCircle) continue;
      const remaining = 30 - (now % 30);
      updateDial(entry.dialCircle, remaining, 30);
    }
    tickLoopHandle = requestAnimationFrame(tick);
  }
  tickLoopHandle = requestAnimationFrame(tick);
}

function digitCellsHTML(code) {
  return String(code).split('').map(d => `<span class="digit">${d}</span>`).join('');
}

function buildRow(acct, index) {
  const row = document.createElement('div');
  row.className = 'ledger-row';
  row.innerHTML = `
    <div class="ledger-index">${String(index + 1).padStart(2, '0')}</div>
    <div class="ledger-id" data-id="${acct.id}">
      <p class="account-issuer">${escapeHtml(acct.issuer)}</p>
      <p class="account-name">${escapeHtml(acct.account_name)}</p>
    </div>
    <div class="ledger-dial">
      ${acct.type === 'totp' ? dialSVG() : `<button class="hotp-btn">NEXT ↻</button>`}
    </div>
    <div class="ledger-code">
      <div class="code-value">${digitCellsHTML(acct.code)}</div>
      <div class="copied-tag">Copied</div>
    </div>
    <button class="card-edit" title="Rename">✎</button>
    <button class="card-remove" title="Remove">✕</button>
  `;

  row.querySelector('.ledger-code').addEventListener('click', () => {
    const entry = cardRegistry.get(acct.id);
    copyCode(entry.data, row);
  });
  row.querySelector('.card-remove').addEventListener('click', (e) => {
    e.stopPropagation();
    removeAccount(acct.id);
  });
  row.querySelector('.card-edit').addEventListener('click', (e) => {
    e.stopPropagation();
    startRename(row, acct);
  });
  const hotpBtn = row.querySelector('.hotp-btn');
  if (hotpBtn) {
    hotpBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await fetch(`/api/accounts/${acct.id}/hotp_next`, { method: 'POST' });
      refreshAccounts();
    });
  }
  return row;
}

function renderIdBlockDisplay(idBlock, issuer, account_name) {
  idBlock.innerHTML = `
    <p class="account-issuer">${escapeHtml(issuer)}</p>
    <p class="account-name">${escapeHtml(account_name)}</p>
  `;
}

function startRename(row, acct) {
  const idBlock = row.querySelector('.ledger-id');
  idBlock.innerHTML = `
    <input type="text" class="rename-input rename-issuer" value="${escapeHtml(acct.issuer)}" placeholder="Issuer (e.g. GitHub)">
    <input type="text" class="rename-input rename-name" value="${escapeHtml(acct.account_name)}" placeholder="Account name (e.g. you@email.com)">
    <div class="rename-actions">
      <button class="rename-save">Save</button>
      <button class="rename-cancel">Cancel</button>
    </div>
  `;

  const issuerInput = idBlock.querySelector('.rename-issuer');
  const nameInput = idBlock.querySelector('.rename-name');
  issuerInput.focus();
  issuerInput.select();

  // refreshAccounts() polls every second but only builds DOM for rows it
  // hasn't seen before - it never rebuilds an existing row's contents back
  // to the display template. So cancel/save must restore the view directly
  // instead of waiting on that poll, or the row gets stuck showing inputs.
  const cancel = (e) => {
    e && e.stopPropagation();
    renderIdBlockDisplay(idBlock, acct.issuer, acct.account_name);
  };

  const save = async (e) => {
    e && e.stopPropagation();
    const issuer = issuerInput.value.trim();
    const account_name = nameInput.value.trim();
    if (!issuer && !account_name) { cancel(); return; }

    const saveBtn = idBlock.querySelector('.rename-save');
    const cancelBtn = idBlock.querySelector('.rename-cancel');
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    saveBtn.textContent = 'Saving…';

    try {
      const res = await fetch(`/api/accounts/${acct.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ issuer, account_name }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        alert(body.error || "Couldn't save that name.");
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
        saveBtn.textContent = 'Save';
        return; // stay in edit mode so the user can fix it and retry
      }
    } catch (err) {
      alert("Couldn't reach the app to save that name.");
      saveBtn.disabled = false;
      cancelBtn.disabled = false;
      saveBtn.textContent = 'Save';
      return;
    }

    // Success: update local state immediately rather than waiting for the
    // next poll, and keep it in sync so a future poll doesn't fight it.
    acct.issuer = issuer;
    acct.account_name = account_name;
    const entry = cardRegistry.get(acct.id);
    if (entry) {
      entry.data.issuer = issuer;
      entry.data.account_name = account_name;
    }
    renderIdBlockDisplay(idBlock, issuer, account_name);
  };

  idBlock.querySelector('.rename-save').addEventListener('click', save);
  idBlock.querySelector('.rename-cancel').addEventListener('click', cancel);
  [issuerInput, nameInput].forEach((input) => {
    input.addEventListener('click', (e) => e.stopPropagation());
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') save(e);
      if (e.key === 'Escape') cancel(e);
    });
  });
}

function dialSVG() {
  const r = 16;
  const circumference = 2 * Math.PI * r;
  let ticks = '';
  for (let i = 0; i < 12; i++) {
    const angle = (i / 12) * 2 * Math.PI;
    const x1 = 22 + Math.cos(angle) * 20;
    const y1 = 22 + Math.sin(angle) * 20;
    const x2 = 22 + Math.cos(angle) * 17.5;
    const y2 = 22 + Math.sin(angle) * 17.5;
    ticks += `<line class="dial-tick" x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}" x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}"/>`;
  }
  return `
    <div class="dial-wrap">
      <svg viewBox="0 0 44 44">
        <g class="dial-ticks-group">${ticks}</g>
        <circle class="dial-track" cx="22" cy="22" r="${r}"></circle>
        <circle class="dial-progress" cx="22" cy="22" r="${r}"
          stroke-dasharray="${circumference}" stroke-dashoffset="0"
          transform="rotate(-90 22 22)"></circle>
      </svg>
    </div>
  `;
}

function updateDial(circle, remaining, total) {
  const r = 16;
  const circumference = 2 * Math.PI * r;
  const fraction = remaining / total;
  circle.style.strokeDashoffset = circumference * (1 - fraction);
  circle.classList.toggle('urgent', remaining <= 5);
}

async function copyCode(acct, rowEl) {
  try {
    await navigator.clipboard.writeText(acct.code);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = acct.code;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
  const tag = rowEl.querySelector('.copied-tag');
  if (tag) {
    tag.classList.add('show');
    setTimeout(() => tag.classList.remove('show'), 1200);
  }
}

async function removeAccount(id) {
  if (!confirm('Remove this account from the vault?')) return;
  await fetch(`/api/accounts/${id}`, { method: 'DELETE' });
  refreshAccounts();
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

// ---------------- Import modal ----------------
const modal = $('#import-modal');

function openModal() {
  modal.classList.remove('hidden');
  $('#import-preview').classList.add('hidden');
  $('#preview-list').innerHTML = '';
  switchTab('camera');
}
function closeModal() {
  modal.classList.add('hidden');
  stopCamera();
}

$('#btn-import').addEventListener('click', openModal);
$('#empty-import-btn').addEventListener('click', openModal);
$('#modal-close').addEventListener('click', closeModal);
modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

$$('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

function switchTab(tab) {
  $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $('#tab-camera').classList.toggle('hidden', tab !== 'camera');
  $('#tab-file').classList.toggle('hidden', tab !== 'file');
  if (tab === 'camera') startCamera(); else stopCamera();
}

// --- Camera scanning ---
async function startCamera() {
  stopCamera();
  const errEl = $('#camera-error');
  errEl.textContent = '';
  const highRes = {
    width: { ideal: 1920 },
    height: { ideal: 1080 }
  };
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment', ...highRes } });
  } catch (e) {
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({ video: { ...highRes } });
    } catch (e2) {
      errEl.textContent = "Couldn't access the camera — check your browser/OS permissions, or use 'Upload image' instead.";
      return;
    }
  }
  const video = $('#camera-video');
  video.srcObject = cameraStream;
  await video.play();

  const canvas = $('#scan-canvas');
  const ctx = canvas.getContext('2d');

  cameraScanLoop = setInterval(() => {
    if (video.readyState !== video.HAVE_ENOUGH_DATA) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imageData.data, imageData.width, imageData.height);
    if (code && code.data) {
      handleScannedText(code.data);
    }
  }, 300);
}

function stopCamera() {
  if (cameraScanLoop) { clearInterval(cameraScanLoop); cameraScanLoop = null; }
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
}

// --- File upload scanning ---
const dropzone = $('#dropzone');
const fileInput = $('#file-input');

// pywebview's macOS backend can't reliably open a native file picker from a
// plain <input type="file"> click, so the packaged desktop app exposes a
// native picker via window.pywebview.api instead. In a normal browser,
// window.pywebview is undefined and we just use the regular file input.
let pickingImage = false;
dropzone.addEventListener('click', async (e) => {
  const errEl = $('#file-error');
  if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_image_base64) {
    // dropzone is a <label> wrapping the hidden file input — clicking a
    // label also auto-fires a click on its wrapped input by default, which
    // (on newer pywebview) opens ANOTHER native dialog on top of this one.
    // Stop that default forwarding since we're handling the pick ourselves.
    e.preventDefault();
    if (pickingImage) return; // ignore rapid double-clicks stacking dialogs
    pickingImage = true;
    errEl.textContent = '';
    try {
      const dataUrl = await window.pywebview.api.pick_image_base64();
      if (dataUrl) handleImageDataUrl(dataUrl);
    } catch (err) {
      console.error('Native file dialog error:', err);
      errEl.textContent = "Couldn't open the file picker: " + err.message;
    } finally {
      pickingImage = false;
    }
    return;
  }
  fileInput.click();
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});
['dragover', 'dragenter'].forEach(evt => {
  dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.add('drag-over'); });
});
['dragleave', 'drop'].forEach(evt => {
  dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.remove('drag-over'); });
});
dropzone.addEventListener('drop', (e) => {
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

function handleFile(file) {
  const errEl = $('#file-error');
  errEl.textContent = '';

  if (typeof jsQR === 'undefined') {
    errEl.textContent = 'The QR scanning library failed to load. Try reloading the app.';
    return;
  }
  if (!file.type.startsWith('image/')) {
    errEl.textContent = 'That file is not an image — upload a screenshot or photo of the QR code.';
    return;
  }

  const reader = new FileReader();
  reader.onerror = () => { errEl.textContent = "Couldn't read that file."; };
  reader.onload = (e) => handleImageDataUrl(e.target.result);
  reader.readAsDataURL(file);
}

function handleImageDataUrl(dataUrl) {
  const errEl = $('#file-error');
  errEl.textContent = '';

  if (typeof jsQR === 'undefined') {
    errEl.textContent = 'The QR scanning library failed to load. Try reloading the app.';
    return;
  }

  const img = new Image();
  img.onerror = () => { errEl.textContent = "That file doesn't look like a valid image."; };
  img.onload = () => {
    try {
      const canvas = $('#scan-canvas');
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      canvas.width = img.width;
      canvas.height = img.height;
      ctx.drawImage(img, 0, 0);
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const code = jsQR(imageData.data, imageData.width, imageData.height);
      if (code && code.data) {
        handleScannedText(code.data);
      } else {
        errEl.textContent = "Couldn't find a QR code in that image. Make sure the whole code is visible, in focus, and not cropped — a direct screenshot works better than a photo of a screen.";
      }
    } catch (err) {
      console.error('QR decode error:', err);
      errEl.textContent = "Something went wrong reading that image: " + err.message;
    }
  };
  img.src = dataUrl;
}

// --- Shared: send decoded QR text to backend for preview ---
let handledOnce = false;
async function handleScannedText(text) {
  if (handledOnce) return; // avoid re-firing repeatedly while camera loop is live
  handledOnce = true;
  stopCamera();

  let data;
  try {
    const res = await fetch('/api/import/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qr_text: text })
    });
    data = await res.json();
  } catch (err) {
    console.error('Import preview request failed:', err);
    const msg = "Couldn't reach the app's local server. Make sure the terminal running `python3 app.py` is still open, then reload this page.";
    $('#camera-error').textContent = msg;
    $('#file-error').textContent = msg;
    handledOnce = false;
    return;
  }

  if (data.error) {
    $('#camera-error').textContent = data.error;
    $('#file-error').textContent = data.error;
    handledOnce = false;
    return;
  }

  const list = $('#preview-list');
  list.innerHTML = data.accounts.map((a, i) => `
    <div class="preview-item">
      <div>
        <div>${escapeHtml(a.issuer)}</div>
        <div class="preview-item-name">${escapeHtml(a.account_name)}</div>
      </div>
      <div class="preview-item-name">${a.type.toUpperCase()}</div>
    </div>
  `).join('');
  $('#import-preview').classList.remove('hidden');
}

$('#confirm-import').addEventListener('click', async () => {
  const res = await fetch('/api/import/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  const data = await res.json();
  if (!data.error) {
    handledOnce = false;
    closeModal();
    refreshAccounts();
  }
});

boot();
