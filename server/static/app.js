// GestorLab - Dashboard do Professor JavaScript

let ws = null;
let clientsMap = new Map(); // id -> clientData
let currentZoomId = null;
let currentMsgTarget = "all";
let currentFileTarget = "all";
let authToken = null;
let currentUser = null;           // {id, email, name, role, must_change}
let forcedPasswordChange = false;  // true enquanto a senha provisória precisa ser trocada
let reconnectTimer = null;
let reconnectDelay = 2000;   // cresce até 15 s enquanto o servidor estiver fora do ar
let isRemoteControlActive = false;
let lastMouseMoveTime = 0;

// Elementos de Login
const loginContainer = document.getElementById("login-container");
const appContainer = document.getElementById("app-container");
const loginForm = document.getElementById("login-form");
const loginEmailInput = document.getElementById("login-email");
const loginPasswordInput = document.getElementById("login-password");
const loginRememberCheckbox = document.getElementById("login-remember");
const loginErrorMsg = document.getElementById("login-error-msg");
const loginErrorText = document.getElementById("login-error-text");
const loginSubmitBtn = document.getElementById("login-submit-btn");
const loginBtnText = document.getElementById("login-btn-text");
const loginBtnIcon = document.getElementById("login-btn-icon");
const loginSpinner = document.getElementById("login-spinner");
const eyeIconOpen = document.getElementById("eye-icon-open");
const eyeIconClosed = document.getElementById("eye-icon-closed");

// Elementos DOM do Dashboard
const pcsGrid = document.getElementById("pcs-grid");
const emptyState = document.getElementById("empty-state");
const onlineCount = document.getElementById("online-count");
const lockedCount = document.getElementById("locked-count");
const serverIpDisplay = document.getElementById("server-ip-display");
const emptyHelpIp = document.getElementById("empty-help-ip");
const searchInput = document.getElementById("search-input");
const toastContainer = document.getElementById("toast-container");

const btnLockAll = document.getElementById("btn-lock-all");
const btnUnlockAll = document.getElementById("btn-unlock-all");
const btnMsgAll = document.getElementById("btn-msg-all");

// Modais
const modalMsg = document.getElementById("modal-msg");
const modalMsgTargetTitle = document.getElementById("modal-msg-target-title");
const modalMsgTitle = document.getElementById("modal-msg-title");
const modalMsgContent = document.getElementById("modal-msg-content");
const modalMsgSendBtn = document.getElementById("modal-msg-send-btn");

const modalFile = document.getElementById("modal-file");
const modalFileTargetTitle = document.getElementById("modal-file-target-title");
const modalFileInput = document.getElementById("modal-file-input");
const modalFileSendBtn = document.getElementById("modal-file-send-btn");
const fileProgressContainer = document.getElementById("file-progress-container");
const fileProgressBar = document.getElementById("file-progress-bar");
const fileProgressPct = document.getElementById("file-progress-pct");

const modalScreen = document.getElementById("modal-screen");
const modalScreenContainer = document.getElementById("modal-screen-container");
const modalScreenImg = document.getElementById("modal-screen-img");
const modalScreenTitle = document.getElementById("modal-screen-title");
const remoteControlBadge = document.getElementById("remote-control-badge");
const zoomBtnRemote = document.getElementById("zoom-btn-remote");
const zoomRemoteText = document.getElementById("zoom-remote-text");

// ==========================================
// Toast Notifications
// ==========================================
function showToast(title, message, type = "info") {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  const bgClass = type === "success" ? "bg-emerald-900/90 border-emerald-500/40 text-emerald-200" :
                  type === "error" ? "bg-red-900/90 border-red-500/40 text-red-200" :
                  type === "warning" ? "bg-amber-900/90 border-amber-500/40 text-amber-200" :
                  "bg-slate-800/95 border-slate-600 text-slate-100";

  toast.className = `${bgClass} backdrop-blur-md border rounded-xl px-4 py-3 shadow-2xl flex items-center space-x-3 text-xs pointer-events-auto transition-all transform duration-300 opacity-0 translate-y-2`;
  const body = document.createElement("div");
  body.className = "flex-1";
  const titleEl = document.createElement("div");
  titleEl.className = "font-bold text-white text-xs";
  titleEl.textContent = title;
  const msgEl = document.createElement("div");
  msgEl.className = "text-[11px] opacity-90";
  msgEl.textContent = message;
  body.append(titleEl, msgEl);
  toast.appendChild(body);

  toastContainer.appendChild(toast);
  requestAnimationFrame(() => {
    toast.classList.remove("opacity-0", "translate-y-2");
  });

  setTimeout(() => {
    toast.classList.add("opacity-0", "translate-y-2");
    setTimeout(() => toast.remove(), 300);
  }, 4500);
}

// ==========================================
// Gerenciamento de Autenticação e Token
// ==========================================
const AUTH_TOKEN_KEY = "gestorlab_auth_token";

function getStoredToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || sessionStorage.getItem(AUTH_TOKEN_KEY);
}

function saveToken(token, remember) {
  if (remember) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
  } else {
    sessionStorage.setItem(AUTH_TOKEN_KEY, token);
    localStorage.removeItem(AUTH_TOKEN_KEY);
  }
}

function clearStoredToken() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  sessionStorage.removeItem(AUTH_TOKEN_KEY);
  authToken = null;
  currentUser = null;
  forcedPasswordChange = false;
  document.body.classList.remove("role-operador");
}

// Chamadas autenticadas à API: o token vai no cabeçalho (não na URL).
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${authToken}` };
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    clearStoredToken();
    showLoginScreen("Sessão expirada. Digite a senha para continuar.");
    throw new Error("unauthorized");
  }
  if (res.status === 403) showToast("Sem permissão", "Seu perfil não permite esta ação.", "warning");
  return res;
}

function jsonBody(payload) {
  return { headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) };
}

function togglePasswordVisibility() {
  if (loginPasswordInput.type === "password") {
    loginPasswordInput.type = "text";
    eyeIconOpen.classList.add("hidden");
    eyeIconClosed.classList.remove("hidden");
  } else {
    loginPasswordInput.type = "password";
    eyeIconOpen.classList.remove("hidden");
    eyeIconClosed.classList.add("hidden");
  }
}

function showLoginScreen(errorMsg = null) {
  if (ws) {
    try { ws.close(); } catch (e) {}
    ws = null;
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  appContainer.classList.add("hidden");
  loginContainer.classList.remove("hidden");

  if (errorMsg) {
    loginErrorText.textContent = errorMsg;
    loginErrorMsg.classList.remove("hidden");
  } else {
    loginErrorMsg.classList.add("hidden");
  }

  loginPasswordInput.value = "";
  loginPasswordInput.focus();
}

function showAppScreen() {
  loginContainer.classList.add("hidden");
  appContainer.classList.remove("hidden");
}

async function handleLoginSubmit(event) {
  if (event) event.preventDefault();

  const email = loginEmailInput.value.trim();
  const password = loginPasswordInput.value;
  const remember = loginRememberCheckbox.checked;

  if (!email || !password) {
    loginErrorText.textContent = "Digite o e-mail e a senha.";
    loginErrorMsg.classList.remove("hidden");
    return;
  }

  loginSubmitBtn.disabled = true;
  loginBtnText.textContent = "Verificando...";
  loginBtnIcon.classList.add("hidden");
  loginSpinner.classList.remove("hidden");
  loginErrorMsg.classList.add("hidden");

  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, remember })
    });

    const data = await res.json();

    if (res.ok && data.success && data.token) {
      saveToken(data.token, remember);
      startSession(data.token, data.user);
    } else {
      loginErrorText.textContent = data.error || "Senha incorreta. Tente novamente.";
      loginErrorMsg.classList.remove("hidden");
      loginPasswordInput.select();
      loginPasswordInput.focus();
    }
  } catch (err) {
    console.error("Erro ao realizar login:", err);
    loginErrorText.textContent = "Não foi possível conectar ao servidor.";
    loginErrorMsg.classList.remove("hidden");
  } finally {
    loginSubmitBtn.disabled = false;
    loginBtnText.textContent = "Acessar Painel";
    loginBtnIcon.classList.remove("hidden");
    loginSpinner.classList.add("hidden");
  }
}

async function checkSavedAuth() {
  const token = getStoredToken();
  if (!token) {
    showLoginScreen();
    return;
  }

  try {
    const res = await fetch("/api/verify-auth", { headers: { Authorization: `Bearer ${token}` } });
    const data = await res.json();
    if (res.ok && data.valid) {
      startSession(token, data.user);
    } else {
      clearStoredToken();
      showLoginScreen("Sessão expirada. Digite a senha para continuar.");
    }
  } catch (e) {
    authToken = token;
    showAppScreen();
    connectWebSocket();
  }
}

function logout() {
  if (confirm("Deseja sair do painel?")) {
    clearStoredToken();
    showLoginScreen();
  }
}

// ==========================================
// Conexão WebSocket com Token
// ==========================================
function connectWebSocket() {
  if (!authToken) {
    showLoginScreen();
    return;
  }

  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/dashboard?token=${encodeURIComponent(authToken)}`;

  const socket = new WebSocket(wsUrl);
  ws = socket;

  ws.onopen = () => {
    console.log("[GestorLab] Conectado e autenticado no servidor.");
    setConnectionBadge(true);
    reconnectDelay = 2000;
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerMessage(data);
    } catch (e) {
      console.error("Erro ao processar mensagem do servidor:", e);
    }
  };

  ws.onclose = (event) => {
    // Uma conexão antiga (fechada no logout ou substituída) não deve agendar outra reconexão.
    if (ws !== socket) return;
    if (event.code === 4001) {
      console.warn("[GestorLab] Conexão rejeitada: Não autorizado (token inválido).");
      clearStoredToken();
      showLoginScreen("Sessão não autorizada ou expirada. Digite a senha.");
      return;
    }

    console.warn(`[GestorLab] Conexão perdida. Tentando reconectar em ${reconnectDelay / 1000}s...`);
    setConnectionBadge(false);
    reconnectTimer = setTimeout(() => {
      if (authToken) {
        connectWebSocket();
      }
    }, reconnectDelay);
    reconnectDelay = Math.min(15000, reconnectDelay * 1.5);
  };

  ws.onerror = (err) => {
    console.error("[GestorLab] Erro no WebSocket:", err);
  };
}

function handleServerMessage(data) {
  switch (data.type) {
    case "init":
      if (data.server_ip) {
        const port = data.server_port || 8000;
        serverIpDisplay.textContent = `${data.server_ip}:${port}`;
        emptyHelpIp.textContent = `ws://${data.server_ip}:${port}/ws/client`;
      }
      clientsMap.clear();
      (data.clients || []).forEach(c => {
        setLockDeadline(c.info, c.info.lock_remaining);
        clientsMap.set(c.id, {
          info: c.info,
          latest_frame: safeFrame(c.latest_frame)
        });
      });
      renderGrid();
      loadStudents();
      loadServerInfo();
      loadRules();
      break;

    case "client_connected":
      const existing = clientsMap.get(data.client.id);
      setLockDeadline(data.client, data.client.lock_remaining);
      clientsMap.set(data.client.id, {
        info: data.client,
        latest_frame: existing ? existing.latest_frame : null
      });
      renderGrid();
      showToast("Novo Computador Conectado", `${data.client.hostname} (${data.client.ip})`, "info");
      break;

    case "client_disconnected":
      const disClient = clientsMap.get(data.client_id);
      const disHost = disClient ? disClient.info.hostname : data.client_id;
      clientsMap.delete(data.client_id);
      if (currentZoomId === data.client_id) {
        closeScreenModal();
      }
      renderGrid();
      showToast("Computador Desconectado", `${disHost}`, "warning");
      break;

    case "screen_frame":
      const client = clientsMap.get(data.client_id);
      if (client) {
        const frame = safeFrame(data.data);
        if (!frame) break;   // quadro inválido: ignora
        client.latest_frame = frame;
        updateCardImage(data.client_id, frame);
        if (currentZoomId === data.client_id) {
          modalScreenImg.src = frame;
        }
      }
      break;

    case "status_update":
      const targetClient = clientsMap.get(data.client_id);
      if (targetClient) {
        targetClient.info.is_locked = data.is_locked;
        setLockDeadline(targetClient.info, data.lock_remaining);
        updateCardStatus(data.client_id, data.is_locked);
        const countdown = document.getElementById(`countdown-${data.client_id}`);
        if (countdown) countdown.textContent = lockCountdownText(targetClient.info);
        updateCounters();
        if (currentZoomId === data.client_id) updateZoomLockBtn();
      }
      break;

    case "rule_violation":
      showToast("Tentativa bloqueada",
        `${data.student_name || data.hostname}: ${data.kind} "${data.detail}" (${data.hostname})`, "warning");
      if (activeNavTab === "rules") loadEvents();
      break;

    case "student_login_update":
      const logClient = clientsMap.get(data.client_id);
      if (logClient) {
        logClient.info.student_name = data.student_name;
        logClient.info.matricula = data.matricula;
        logClient.info.is_student_logged_in = data.is_student_logged_in;
        logClient.info.turma = data.turma || "";
        renderGrid();
        if (data.is_student_logged_in && data.student_name) {
          showToast("Aluno Identificado", `${data.student_name} (${data.matricula}) em ${logClient.info.hostname}`, "success");
        }
      }
      break;

    case "file_transfer_status":
      const fileClient = clientsMap.get(data.client_id);
      const clientName = fileClient ? fileClient.info.hostname : data.client_id;
      if (data.status === "ok") {
        showToast("Arquivo Entregue com Sucesso!", `'${data.filename}' salvo em ${clientName}`, "success");
      } else {
        showToast("Falha na Entrega do Arquivo", `Erro ao salvar em ${clientName}`, "error");
      }
      break;
  }
}

function sendCommand(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
  } else {
    showToast("Sem Conexão", "Não conectado ao servidor no momento.", "error");
  }
}

function updateCounters() {
  const total = clientsMap.size;
  let locked = 0;
  clientsMap.forEach(c => {
    if (c.info.is_locked) locked++;
  });
  onlineCount.textContent = total;
  lockedCount.textContent = locked;
}

// O quadro vem do computador do aluno: só aceita JPEG em base64 (qualquer outra coisa pode ser um ataque).
const FRAME_RE = /^data:image\/jpeg;base64,[A-Za-z0-9+\/]+={0,2}$/;
function safeFrame(value) {
  return typeof value === "string" && FRAME_RE.test(value) ? value : null;
}

function updateCardImage(clientId, frameData) {
  const imgEl = document.getElementById(`screen-${clientId}`);
  if (imgEl && frameData) {
    imgEl.src = frameData;
  }
}

function updateCardStatus(clientId, isLocked) {
  const card = document.getElementById(`card-${clientId}`);
  if (!card) return;

  const overlay = document.getElementById(`overlay-${clientId}`);
  const lockBtn = document.getElementById(`btn-toggle-lock-${clientId}`);

  if (isLocked) {
    overlay.classList.remove("hidden");
    lockBtn.innerHTML = `
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"/>
      </svg>
      <span>Desbloquear</span>
    `;
    lockBtn.className = "flex-1 flex items-center justify-center space-x-1 bg-emerald-600/80 hover:bg-emerald-600 text-white text-xs font-medium py-1.5 px-2 rounded-lg transition";
  } else {
    overlay.classList.add("hidden");
    lockBtn.innerHTML = `
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
      </svg>
      <span>Bloquear</span>
    `;
    lockBtn.className = "flex-1 flex items-center justify-center space-x-1 bg-red-600/80 hover:bg-red-600 text-white text-xs font-medium py-1.5 px-2 rounded-lg transition";
  }
}

// ==========================================
// Renderização da Grade de Computadores
// ==========================================
function renderGrid() {
  updateCounters();

  updateTurmaOptions();
  const query = (searchInput.value || "").toLowerCase().trim();
  const filtered = Array.from(clientsMap.values()).filter(c => {
    if (groupFilter && (c.info.turma || "").trim().toLowerCase() !== groupFilter.toLowerCase()) return false;
    const sName = (c.info.student_name || "").toLowerCase();
    const sMat = (c.info.matricula || "").toLowerCase();
    const host = (c.info.hostname || "").toLowerCase();
    const ip = c.info.ip || "";
    return host.includes(query) || sName.includes(query) || sMat.includes(query) || ip.includes(query);
  });

  if (clientsMap.size === 0) {
    emptyState.classList.remove("hidden");
    pcsGrid.classList.add("hidden");
    return;
  }

  emptyState.classList.add("hidden");
  pcsGrid.classList.remove("hidden");
  pcsGrid.innerHTML = "";

  if (filtered.length === 0) {
    const none = document.createElement("div");
    none.className = "col-span-full text-center text-sm text-slate-400 py-12";
    none.textContent = groupFilter && !searchInput.value.trim()
      ? `Nenhum aluno da turma "${groupFilter}" conectado agora.`
      : `Nenhum computador corresponde a "${searchInput.value.trim()}".`;
    pcsGrid.appendChild(none);
    return;
  }

  filtered.forEach(c => {
    const info = c.info;
    const card = document.createElement("div");
    card.id = `card-${info.id}`;
    card.dataset.clientId = info.id;
    card.className = "bg-slate-800 border border-slate-700 rounded-2xl overflow-hidden shadow-lg flex flex-col hover:border-slate-500 transition-all duration-200 group";

    const isLocked = info.is_locked;
    const hostE = escapeHtml(info.hostname);
    const ipE = escapeHtml(info.ip);
    const idE = escapeHtml(info.id);
    const PLACEHOLDER_IMG = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='320' height='180' viewBox='0 0 320 180'><rect width='100%' height='100%' fill='%230f172a'/><text x='50%' y='50%' fill='%23475569' font-size='12' font-family='sans-serif' text-anchor='middle'>Aguardando sinal de tela...</text></svg>";

    // Badge do Aluno
    const hasStudent = info.student_name && info.student_name.trim().length > 0;
    const studentBadge = hasStudent ? `
      <div class="px-3 py-1 bg-indigo-950/70 border-b border-indigo-500/20 flex items-center justify-between text-[11px]">
        <div class="flex items-center space-x-1.5 text-indigo-300 font-semibold truncate">
          <span>🎓</span>
          <span class="truncate">${escapeHtml(info.student_name)}</span>
          <span class="text-indigo-400 font-normal">(${escapeHtml(info.matricula)})</span>
          ${info.turma ? `<span class="ml-1 bg-indigo-500/20 border border-indigo-500/30 text-indigo-200 px-1.5 rounded-full font-normal">${escapeHtml(info.turma)}</span>` : ""}
        </div>
        <button data-action="logout" title="Desconectar este aluno e pedir login novamente" class="text-indigo-400 hover:text-white ml-1">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7"/></svg>
        </button>
      </div>
    ` : `
      <div class="px-3 py-1 bg-amber-950/40 border-b border-amber-500/20 flex items-center justify-between text-[11px] text-amber-300">
        <div class="flex items-center space-x-1.5">
          <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
          <span>Aguardando Login do Aluno</span>
        </div>
        <button data-action="bypass" title="Liberar sem exigir identificação" class="text-amber-400 hover:text-white underline text-[10px]">
          Liberar
        </button>
      </div>
    `;

    card.innerHTML = `
      <!-- Card Header -->
      <div class="px-3.5 py-2.5 bg-slate-800/95 border-b border-slate-700/80 flex items-center justify-between">
        <div class="flex items-center space-x-2 truncate">
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-sm shadow-emerald-400"></span>
          <span class="font-semibold text-sm text-white truncate" title="${hostE}">${hostE}</span>
        </div>
        <span class="text-[11px] font-mono text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-700/60">${ipE}</span>
      </div>

      <!-- Aluno Info Badge -->
      ${studentBadge}

      <!-- Screen Preview Area -->
      <div class="relative bg-black aspect-video flex items-center justify-center overflow-hidden cursor-pointer" data-action="zoom">
        <img id="screen-${idE}" src="${PLACEHOLDER_IMG}" alt="${hostE}" class="w-full h-full object-contain">
        
        <!-- Lock Overlay -->
        <div id="overlay-${idE}" class="absolute inset-0 bg-red-950/85 backdrop-blur-xs flex flex-col items-center justify-center text-white ${isLocked ? '' : 'hidden'}">
          <svg class="w-8 h-8 text-red-400 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
          </svg>
          <span class="text-xs font-bold tracking-wide uppercase text-red-300">Bloqueado</span>
          <span id="countdown-${idE}" class="text-[11px] font-semibold text-amber-300 mt-0.5">${lockCountdownText(info)}</span>
        </div>

        <!-- Hover Zoom Hint -->
        <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition flex items-center justify-center pointer-events-none">
          <span class="bg-slate-900/90 text-white text-xs px-3 py-1.5 rounded-full border border-slate-700 flex items-center space-x-1.5 shadow-lg">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v6m3-3H7"/>
            </svg>
            <span>Expandir & Controle</span>
          </span>
        </div>
      </div>

      <!-- Card Actions -->
      <div class="p-2.5 bg-slate-850 border-t border-slate-700/60 flex items-center space-x-1.5">
        <!-- Bloquear / Desbloquear -->
        <button id="btn-toggle-lock-${idE}" data-action="toggle-lock" 
                class="flex-1 flex items-center justify-center space-x-1 ${isLocked ? 'bg-emerald-600/80 hover:bg-emerald-600' : 'bg-red-600/80 hover:bg-red-600'} text-white text-xs font-medium py-1.5 px-2 rounded-lg transition" title="Bloquear ou Desbloquear">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${isLocked ? 'M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z' : 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z'}"/>
          </svg>
          <span>${isLocked ? 'Desbloquear' : 'Bloquear'}</span>
        </button>

        <!-- Mensagem -->
        <button data-action="msg" 
                class="bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium p-1.5 rounded-lg transition flex items-center justify-center" title="Enviar mensagem individual">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
          </svg>
        </button>

        <!-- Enviar Arquivo -->
        <button data-action="file" 
                class="bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium p-1.5 rounded-lg transition flex items-center justify-center" title="Enviar arquivo para este PC">
          <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
          </svg>
        </button>

        <!-- Reiniciar -->
        <button data-action="reboot" 
                class="bg-slate-700 hover:bg-amber-600/80 text-slate-200 text-xs font-medium p-1.5 rounded-lg transition flex items-center justify-center" title="Reiniciar este computador">
          <svg class="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
        </button>

        <!-- Desligar -->
        <button data-action="shutdown" 
                class="bg-slate-700 hover:bg-rose-600/80 text-slate-200 text-xs font-medium p-1.5 rounded-lg transition flex items-center justify-center" title="Desligar este computador">
          <svg class="w-4 h-4 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
          </svg>
        </button>
      </div>
    `;

    const preview = card.querySelector("img");
    if (c.latest_frame && preview) preview.src = c.latest_frame;   // via DOM, nunca como texto de HTML
    pcsGrid.appendChild(card);
  });
}

// Um único listener para os botões dos cartões: ids e hostnames não entram em atributos onclick.
pcsGrid.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  const card = btn && btn.closest("[data-client-id]");
  if (!card) return;
  const id = card.dataset.clientId;
  const client = clientsMap.get(id);
  if (!client) return;
  const host = client.info.hostname;
  switch (btn.dataset.action) {
    case "logout": forceStudentLogout(id); break;
    case "bypass": bypassStudentLogin(id); break;
    case "zoom": openScreenModal(id, host); break;
    case "toggle-lock": toggleLock(id); break;
    case "msg": openMsgModal(id, host); break;
    case "file": openFileModal(id, host); break;
    case "reboot": confirmPowerAction(id, "reboot", host); break;
    case "shutdown": confirmPowerAction(id, "shutdown", host); break;
  }
});

function toggleLock(clientId) {
  const client = clientsMap.get(clientId);
  if (!client) return;
  const isLockedNow = client.info.is_locked;
  const action = isLockedNow ? "unlock" : "lock";

  sendCommand({
    action: action,
    target: clientId,
    message: "Atenção na explicação do professor."
  });
}

function forceStudentLogout(clientId) {
  if (confirm("Deseja desconectar este aluno e pedir login novamente?")) {
    sendCommand({
      action: "student_logout",
      target: clientId
    });
    showToast("Solicitação Enviada", "Tela de identificação aberta no computador do aluno.", "info");
  }
}

function bypassStudentLogin(clientId) {
  sendCommand({
    action: "bypass_student_login",
    target: clientId
  });
  showToast("Aluno Liberado", "O computador foi liberado sem exigir login.", "success");
}

// ==========================================
// Gerenciamento de Energia (Desligar / Reiniciar)
// ==========================================
function confirmPowerAction(target, mode, targetName) {
  const actionName = mode === "shutdown" ? "DESLIGAR" : "REINICIAR";
  const isGroup = target === "all" || String(target).startsWith("turma:");
  const confirmMsg = isGroup
    ? `⚠️ ATENÇÃO: Deseja realmente ${actionName} TODOS os computadores de: ${targetName}?`
    : `Deseja realmente ${actionName} o computador ${targetName}?`;

  if (confirm(confirmMsg)) {
    sendCommand({
      action: "power",
      target: target,
      mode: mode
    });
    showToast(`Comando de ${mode === "shutdown" ? "Desligamento" : "Reinicialização"} Enviado`, `Alvo: ${targetName}`, "warning");
  }
}

// Global button actions
btnLockAll.onclick = () => openLockModal();

btnUnlockAll.onclick = () => {
  sendCommand({
    action: "unlock",
    target: groupTarget()
  });
};

btnMsgAll.onclick = () => {
  openMsgModal(groupTarget(), groupLabel());
};

// ==========================================
// Modal de Mensagem
// ==========================================
function openMsgModal(targetId, targetName) {
  currentMsgTarget = targetId;
  modalMsgTargetTitle.textContent = `Enviar Mensagem para: ${targetName}`;
  modalMsgContent.value = "";
  modalMsg.classList.remove("hidden");
  modalMsgContent.focus();
}

function closeMsgModal() {
  modalMsg.classList.add("hidden");
}

modalMsgSendBtn.onclick = () => {
  const title = modalMsgTitle.value.trim() || "Aviso do Professor";
  const content = modalMsgContent.value.trim();
  if (!content) {
    alert("Digite o conteúdo da mensagem.");
    return;
  }

  sendCommand({
    action: "message",
    target: currentMsgTarget,
    title: title,
    content: content
  });

  closeMsgModal();
  showToast("Mensagem Enviada", `Entregue com sucesso.`, "success");
};

// ==========================================
// Modal de Envio de Arquivos
// ==========================================
function openFileModal(targetId, targetName) {
  currentFileTarget = targetId;
  modalFileTargetTitle.textContent = `Enviar Arquivo para: ${targetName}`;
  modalFileInput.value = "";
  fileProgressContainer.classList.add("hidden");
  fileProgressBar.style.width = "0%";
  modalFileSendBtn.disabled = false;
  modalFileSendBtn.textContent = "Enviar Arquivo";
  modalFile.classList.remove("hidden");
}

function closeFileModal() {
  modalFile.classList.add("hidden");
}

async function submitFileTransfer() {
  if (!modalFileInput.files || modalFileInput.files.length === 0) {
    alert("Por favor, selecione um arquivo.");
    return;
  }

  const file = modalFileInput.files[0];
  const formData = new FormData();
  formData.append("file", file);
  formData.append("target", currentFileTarget);

  if (maxUploadMb && file.size > maxUploadMb * 1024 * 1024) {
    alert(`O arquivo tem ${(file.size / 1048576).toFixed(1)} MB. O limite é ${maxUploadMb} MB.`);
    return;
  }

  modalFileSendBtn.disabled = true;
  modalFileSendBtn.textContent = "Enviando...";
  fileProgressContainer.classList.remove("hidden");
  fileProgressBar.style.width = "0%";
  fileProgressPct.textContent = "0%";

  try {
    // XHR (e não fetch) para mostrar o progresso real do envio.
    const { status, data } = await uploadWithProgress("/api/file-transfer", formData, (pct) => {
      fileProgressBar.style.width = `${pct}%`;
      fileProgressPct.textContent = pct < 100 ? `${pct}%` : "Entregando aos computadores...";
    });
    const res = { ok: status >= 200 && status < 300 };
    if (status === 401) {
      clearStoredToken();
      showLoginScreen("Sessão expirada. Digite a senha para continuar.");
      return;
    }
    if (res.ok && data.success) {
      fileProgressBar.style.width = "100%";
      fileProgressPct.textContent = "100% Concluído!";
      setTimeout(() => {
        closeFileModal();
        showToast("Arquivo Enviado com Sucesso!", `'${data.filename}' transmitido para ${data.sent_count} computador(es).`, "success");
      }, 500);
    } else {
      alert(data.detail || "Erro ao transferir arquivo.");
      modalFileSendBtn.disabled = false;
      modalFileSendBtn.textContent = "Tentar Novamente";
    }
  } catch (err) {
    console.error("Erro na transferência de arquivo:", err);
    alert("Erro de conexão ao enviar o arquivo.");
    modalFileSendBtn.disabled = false;
    modalFileSendBtn.textContent = "Tentar Novamente";
  }
}

// ==========================================
// Modal de Zoom de Tela & Controle Remoto Interativo
// ==========================================
function openScreenModal(clientId, hostname) {
  currentZoomId = clientId;
  modalScreenTitle.textContent = `Ao Vivo: ${hostname}`;
  const client = clientsMap.get(clientId);
  if (client && client.latest_frame) {
    modalScreenImg.src = client.latest_frame;
  } else {
    modalScreenImg.src = BLANK_IMG;   // src="" faria o navegador pedir a própria página
  }
  modalScreen.classList.remove("hidden");
  updateZoomLockBtn();
  deactivateRemoteControl();

  // Aumenta o FPS e resolução deste aluno para tela cheia fluida
  sendCommand({
    action: "set_stream_settings",
    target: clientId,
    interval: 0.08,
    scale: 0.75,
    quality: 55
  });
}

function closeScreenModal() {
  deactivateRemoteControl();
  if (currentZoomId) {
    const defaultInterval = fpsSelector ? parseFloat(fpsSelector.value) : 0.5;
    sendCommand({
      action: "set_stream_settings",
      target: currentZoomId,
      interval: defaultInterval,
      scale: 0.4,
      quality: 40
    });
  }
  modalScreen.classList.add("hidden");
  currentZoomId = null;
}

function updateZoomLockBtn() {
  const btn = document.getElementById("zoom-btn-lock");
  if (!btn || !currentZoomId) return;
  const client = clientsMap.get(currentZoomId);
  if (!client) return;

  if (client.info.is_locked) {
    btn.className = "flex items-center space-x-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-2.5 py-1.5 rounded-lg border border-emerald-500/50 transition";
    btn.innerHTML = `
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"/>
      </svg>
      <span>Desbloquear</span>
    `;
  } else {
    btn.className = "flex items-center space-x-1 bg-red-600 hover:bg-red-500 text-white text-xs font-semibold px-2.5 py-1.5 rounded-lg border border-red-500/50 transition";
    btn.innerHTML = `
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
      </svg>
      <span>Bloquear</span>
    `;
  }
}

function zoomToggleLock() {
  if (!currentZoomId) return;
  const client = clientsMap.get(currentZoomId);
  if (!client) return;
  const action = client.info.is_locked ? "unlock" : "lock";
  sendCommand({
    action: action,
    target: currentZoomId,
    message: "Atenção na explicação do professor."
  });
}

function zoomSendMsg() {
  if (!currentZoomId) return;
  const client = clientsMap.get(currentZoomId);
  const hostname = client ? client.info.hostname : currentZoomId;
  openMsgModal(currentZoomId, hostname);
}

function zoomSendFile() {
  if (!currentZoomId) return;
  const client = clientsMap.get(currentZoomId);
  const hostname = client ? client.info.hostname : currentZoomId;
  openFileModal(currentZoomId, hostname);
}

function zoomReboot() {
  if (!currentZoomId) return;
  const client = clientsMap.get(currentZoomId);
  const hostname = client ? client.info.hostname : currentZoomId;
  confirmPowerAction(currentZoomId, "reboot", hostname);
}

function zoomShutdown() {
  if (!currentZoomId) return;
  const client = clientsMap.get(currentZoomId);
  const hostname = client ? client.info.hostname : currentZoomId;
  confirmPowerAction(currentZoomId, "shutdown", hostname);
}

// ==========================================
// Lógica de Controle Remoto (Mouse e Teclado)
// ==========================================
function toggleRemoteControl() {
  if (isRemoteControlActive) {
    deactivateRemoteControl();
  } else {
    activateRemoteControl();
  }
}

function activateRemoteControl() {
  if (!currentZoomId) return;
  isRemoteControlActive = true;
  modalScreenImg.classList.add("remote-active");
  remoteControlBadge.classList.remove("hidden");
  zoomBtnRemote.className = "flex items-center space-x-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg border border-emerald-400 shadow-md shadow-emerald-500/20 transition animate-pulse";
  zoomRemoteText.textContent = "Controle Ativo (Clique p/ Sair)";
  showToast("Controle Remoto Ativado", "Movimentos, cliques e teclas serão replicados no aluno.", "success");
}

function deactivateRemoteControl() {
  isRemoteControlActive = false;
  modalScreenImg.classList.remove("remote-active");
  remoteControlBadge.classList.add("hidden");
  zoomBtnRemote.className = "flex items-center space-x-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-600 transition";
  zoomRemoteText.textContent = "Assumir Controle Remoto";
}

// Tratamento de Movimento e Cliques na Imagem
function calculateImageCoordinates(e) {
  const rect = modalScreenImg.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;

  const clientX = e.clientX;
  const clientY = e.clientY;

  if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
    return null;
  }

  const x_ratio = (clientX - rect.left) / rect.width;
  const y_ratio = (clientY - rect.top) / rect.height;

  return {
    x: Math.max(0, Math.min(1, x_ratio)),
    y: Math.max(0, Math.min(1, y_ratio))
  };
}

modalScreenImg.addEventListener("mousemove", (e) => {
  if (!isRemoteControlActive || !currentZoomId) return;
  const now = Date.now();
  if (now - lastMouseMoveTime < 25) return; // Throttling 40 FPS para movimento do mouse
  lastMouseMoveTime = now;

  const coords = calculateImageCoordinates(e);
  if (!coords) return;

  sendCommand({
    action: "remote_input",
    target: currentZoomId,
    event: "mouse_move",
    x: coords.x,
    y: coords.y
  });
});

modalScreenImg.addEventListener("mousedown", (e) => {
  if (!isRemoteControlActive || !currentZoomId) return;
  e.preventDefault();
  const coords = calculateImageCoordinates(e);
  if (!coords) return;

  sendCommand({
    action: "remote_input",
    target: currentZoomId,
    event: "mouse_down",
    button: e.button,
    x: coords.x,
    y: coords.y
  });
});

modalScreenImg.addEventListener("mouseup", (e) => {
  if (!isRemoteControlActive || !currentZoomId) return;
  e.preventDefault();
  const coords = calculateImageCoordinates(e);
  if (!coords) return;

  sendCommand({
    action: "remote_input",
    target: currentZoomId,
    event: "mouse_up",
    button: e.button,
    x: coords.x,
    y: coords.y
  });
});

modalScreenImg.addEventListener("contextmenu", (e) => {
  if (isRemoteControlActive) {
    e.preventDefault(); // Evita o menu do navegador para passar o clique direito ao aluno
  }
});

modalScreenContainer.addEventListener("wheel", (e) => {
  if (!isRemoteControlActive || !currentZoomId) return;
  e.preventDefault();
  sendCommand({
    action: "remote_input",
    target: currentZoomId,
    event: "wheel",
    deltaY: e.deltaY
  });
}, { passive: false });

// Captura de Teclado no Controle Remoto
window.addEventListener("keydown", (e) => {
  if (!isRemoteControlActive || !currentZoomId) {
    if (e.key === "Escape") closeTopModal();
    return;
  }

  // Se pressionar ESC durante o controle remoto, desativa o controle remoto
  if (e.key === "Escape") {
    deactivateRemoteControl();
    showToast("Controle Remoto Encerrado", "Pressione novamente ESC para fechar a tela.", "info");
    return;
  }

  // Ignora F12 para desenvolvedores
  if (e.key === "F12") return;

  e.preventDefault();
  sendCommand({
    action: "remote_input",
    target: currentZoomId,
    event: "key_down",
    key: e.key,
    code: e.code,
    ctrl: e.ctrlKey,
    alt: e.altKey,
    meta: e.metaKey
  });
});

window.addEventListener("keyup", (e) => {
  if (!isRemoteControlActive || !currentZoomId) return;
  if (e.key === "Escape" || e.key === "F12") return;

  e.preventDefault();
  sendCommand({
    action: "remote_input",
    target: currentZoomId,
    event: "key_up",
    key: e.key,
    code: e.code,
    ctrl: e.ctrlKey,
    alt: e.altKey,
    meta: e.metaKey
  });
});

searchInput.addEventListener("input", renderGrid);

// Seletor Global de FPS
const fpsSelector = document.getElementById("fps-selector");
if (fpsSelector) {
  fpsSelector.addEventListener("change", (e) => {
    const interval = parseFloat(e.target.value);
    sendCommand({
      action: "set_stream_settings",
      target: "all",
      interval: interval
    });
  });
}

// ==========================================
// Utilitários
// ==========================================
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ==========================================
// Gestão de Abas de Navegação (Computadores / Alunos)
// ==========================================
let activeNavTab = "monitoring";

const NAV_TABS = ["monitoring", "students", "attendance", "rules", "team"];
const NAV_ACTIVE = "flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white shadow-md transition";
const NAV_IDLE = "flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white hover:bg-slate-800 transition";

function switchNavTab(tab) {
  activeNavTab = tab;
  NAV_TABS.forEach(name => {
    // A aba Equipe é só de administradores: a classe "admin-only" precisa sobreviver à troca de estilo.
    document.getElementById(`tab-btn-${name}`).className = ((name === tab) ? NAV_ACTIVE : NAV_IDLE) + (name === "team" ? " admin-only" : "");
    document.getElementById(`view-${name}`).classList.toggle("hidden", name !== tab);
  });
  // Os botões globais (bloquear sala, FPS...) só fazem sentido na aba de computadores.
  const actions = document.getElementById("monitoring-actions");
  if (actions) actions.classList.toggle("hidden", tab !== "monitoring");

  if (tab === "students") loadStudents();
  if (tab === "attendance") loadAttendance();
  if (tab === "rules") { loadRules(); loadEvents(); }
  if (tab === "team") { loadUsers(); loadAudit(); }
}

// ==========================================
// Gestão de Alunos (CRUD)
// ==========================================
let studentsList = [];
let selectedStudentIds = new Set();
let studentDeleteTarget = null;
let studentSearchTimeout = null;

async function loadStudents(query = "") {
  if (!authToken) return;
  try {
    const q = query ? `?q=${encodeURIComponent(query)}` : "";
    const res = await api(`/api/students${q}`);
    const data = await res.json();
    if (res.ok && data.success) {
      studentsList = data.students || [];
      updateStudentsCountBadge(studentsList.length);
      renderStudentsTable();
    }
  } catch (e) {
    console.error("Erro ao carregar alunos:", e);
  }
}

function updateStudentsCountBadge(total) {
  const tabCount = document.getElementById("tab-students-count");
  const badgeCount = document.getElementById("students-badge-count");
  if (tabCount) tabCount.textContent = total;
  if (badgeCount) badgeCount.textContent = `${total} aluno${total === 1 ? '' : 's'}`;
}

function handleStudentSearch(event) {
  const val = event.target.value;
  clearTimeout(studentSearchTimeout);
  studentSearchTimeout = setTimeout(() => {
    loadStudents(val);
  }, 250);
}

function renderStudentsTable() {
  const tbody = document.getElementById("students-table-body");
  const emptyState = document.getElementById("students-empty-state");
  const selectAll = document.getElementById("students-select-all");
  if (!tbody) return;

  if (studentsList.length === 0) {
    tbody.innerHTML = "";
    if (emptyState) emptyState.classList.remove("hidden");
    if (selectAll) selectAll.checked = false;
    updateBulkDeleteButton();
    return;
  }

  if (emptyState) emptyState.classList.add("hidden");

  let allChecked = selectedStudentIds.size > 0;
  tbody.innerHTML = studentsList.map(s => {
    const isChecked = selectedStudentIds.has(s.id);
    if (!isChecked) allChecked = false;

    const parts = s.name.trim().split(" ");
    const initials = escapeHtml(parts.length > 1 ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase() : parts[0].slice(0, 2).toUpperCase());

    return `
      <tr class="hover:bg-slate-700/30 transition border-b border-slate-700/40">
        <td class="py-3 px-4 text-center">
          <input type="checkbox" ${isChecked ? "checked" : ""} onchange="toggleSelectStudent(${s.id}, this)" class="w-4 h-4 rounded bg-slate-950 border-slate-700 text-indigo-600 focus:ring-indigo-500 accent-indigo-600 cursor-pointer">
        </td>
        <td class="py-3 px-4 font-mono font-semibold text-indigo-300">
          <span class="bg-indigo-950/60 border border-indigo-500/30 px-2 py-0.5 rounded text-xs">${escapeHtml(s.matricula)}</span>
        </td>
        <td class="py-3 px-4 font-medium text-white">
          <div class="flex items-center space-x-2.5">
            <div class="w-7 h-7 rounded-full bg-indigo-600/30 border border-indigo-500/40 text-indigo-300 text-xs font-bold flex items-center justify-center shrink-0">
              ${initials}
            </div>
            <span class="truncate max-w-xs">${escapeHtml(s.name)}</span>
          </div>
        </td>
        <td class="py-3 px-4 text-slate-300">
          ${s.turma ? `<span class="bg-slate-900 border border-slate-700 text-slate-300 text-xs px-2 py-0.5 rounded-full">${escapeHtml(s.turma)}</span>` : '<span class="text-slate-500 text-xs italic">Não informada</span>'}
        </td>
        <td class="py-3 px-4 text-xs text-slate-400">
          ${escapeHtml(s.created_at) || '-'}
        </td>
        <td class="py-3 px-4 text-right">
          <div class="flex items-center justify-end space-x-1">
            <button onclick="openEditStudentModal(${s.id})" title="Editar Aluno" class="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-700/60 rounded-lg transition cursor-pointer">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/>
              </svg>
            </button>
            <button onclick="openDeleteStudentModal(${s.id})" title="Excluir Aluno" class="admin-only p-1.5 text-slate-400 hover:text-red-400 hover:bg-slate-700/60 rounded-lg transition cursor-pointer">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  if (selectAll) selectAll.checked = allChecked && studentsList.length > 0;
  updateBulkDeleteButton();
}

function toggleSelectStudent(id, checkbox) {
  if (checkbox.checked) {
    selectedStudentIds.add(id);
  } else {
    selectedStudentIds.delete(id);
  }
  const selectAll = document.getElementById("students-select-all");
  if (selectAll) {
    selectAll.checked = selectedStudentIds.size === studentsList.length && studentsList.length > 0;
  }
  updateBulkDeleteButton();
}

function toggleSelectAllStudents(masterCheckbox) {
  if (masterCheckbox.checked) {
    studentsList.forEach(s => selectedStudentIds.add(s.id));
  } else {
    selectedStudentIds.clear();
  }
  renderStudentsTable();
}

function updateBulkDeleteButton() {
  const btn = document.getElementById("btn-bulk-delete-students");
  const count = document.getElementById("bulk-delete-count");
  if (!btn || !count) return;

  if (selectedStudentIds.size > 0) {
    count.textContent = selectedStudentIds.size;
    btn.classList.remove("hidden");
    btn.classList.add("flex");
  } else {
    btn.classList.add("hidden");
    btn.classList.remove("flex");
  }
}

function openCreateStudentModal() {
  document.getElementById("student-form-id").value = "";
  document.getElementById("modal-student-title").innerHTML = `
    <svg class="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"/>
    </svg>
    <span>Cadastrar Novo Aluno</span>
  `;
  document.getElementById("student-form-name").value = "";
  document.getElementById("student-form-matricula").value = "";
  document.getElementById("student-form-turma").value = "";
  const passInput = document.getElementById("student-form-password");
  passInput.value = "";
  passInput.required = true;
  document.getElementById("student-form-pass-req").classList.remove("hidden");
  document.getElementById("student-form-pass-hint").classList.add("hidden");
  document.getElementById("student-form-error").classList.add("hidden");

  document.getElementById("modal-student-form").classList.remove("hidden");
  setTimeout(() => document.getElementById("student-form-name").focus(), 100);
}

function openEditStudentModal(id) {
  const student = studentsList.find(s => s.id === id);
  if (!student) return;

  document.getElementById("student-form-id").value = student.id;
  document.getElementById("modal-student-title").innerHTML = `
    <svg class="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
    </svg>
    <span>Editar Aluno</span>
  `;
  document.getElementById("student-form-name").value = student.name;
  document.getElementById("student-form-matricula").value = student.matricula;
  document.getElementById("student-form-turma").value = student.turma || "";
  const passInput = document.getElementById("student-form-password");
  passInput.value = "";
  passInput.required = false;
  document.getElementById("student-form-pass-req").classList.add("hidden");
  document.getElementById("student-form-pass-hint").classList.remove("hidden");
  document.getElementById("student-form-error").classList.add("hidden");

  document.getElementById("modal-student-form").classList.remove("hidden");
  setTimeout(() => document.getElementById("student-form-name").focus(), 100);
}

function closeStudentModal() {
  document.getElementById("modal-student-form").classList.add("hidden");
}

function toggleStudentPasswordVisibility() {
  const inp = document.getElementById("student-form-password");
  const open = document.getElementById("student-pass-eye-open");
  const closed = document.getElementById("student-pass-eye-closed");
  if (inp.type === "password") {
    inp.type = "text";
    open.classList.add("hidden");
    closed.classList.remove("hidden");
  } else {
    inp.type = "password";
    open.classList.remove("hidden");
    closed.classList.add("hidden");
  }
}

async function submitStudentForm(event) {
  event.preventDefault();
  const id = document.getElementById("student-form-id").value;
  const name = document.getElementById("student-form-name").value.trim();
  const matricula = document.getElementById("student-form-matricula").value.trim();
  const turma = document.getElementById("student-form-turma").value.trim();
  const password = document.getElementById("student-form-password").value;

  const errorBox = document.getElementById("student-form-error");
  const errorText = document.getElementById("student-form-error-text");
  const saveBtn = document.getElementById("student-form-save-btn");

  if (!name || !matricula) {
    errorText.textContent = "Nome e matrícula são obrigatórios.";
    errorBox.classList.remove("hidden");
    return;
  }

  if (!id && !password) {
    errorText.textContent = "A senha é obrigatória para novos alunos.";
    errorBox.classList.remove("hidden");
    return;
  }

  saveBtn.disabled = true;
  errorBox.classList.add("hidden");

  try {
    let res;
    if (id) {
      const payload = { name, matricula, turma };
      if (password.trim()) payload.password = password.trim();
      res = await api(`/api/students/${id}`, { method: "PUT", ...jsonBody(payload) });
    } else {
      res = await api("/api/students", { method: "POST", ...jsonBody({ name, matricula, turma, password }) });
    }

    const data = await res.json();
    if (res.ok && data.success) {
      closeStudentModal();
      showToast("Sucesso", id ? "Aluno atualizado com sucesso!" : "Aluno cadastrado com sucesso!", "success");
      await loadStudents();
    } else {
      errorText.textContent = data.error || "Ocorreu um erro ao salvar o aluno.";
      errorBox.classList.remove("hidden");
    }
  } catch (e) {
    errorText.textContent = "Erro de conexão com o servidor.";
    errorBox.classList.remove("hidden");
  } finally {
    saveBtn.disabled = false;
  }
}

function openDeleteStudentModal(id) {
  const student = studentsList.find(s => s.id === id);
  const name = student ? student.name : "";
  studentDeleteTarget = { mode: "single", id, name };
  document.getElementById("modal-delete-title").textContent = "Excluir Aluno";
  document.getElementById("modal-delete-desc").textContent = `Tem certeza de que deseja excluir o aluno "${name}"? As credenciais dele serão revogadas imediatamente.`;
  document.getElementById("modal-student-delete").classList.remove("hidden");
}

function confirmBulkDeleteStudents() {
  if (selectedStudentIds.size === 0) return;
  studentDeleteTarget = { mode: "bulk", count: selectedStudentIds.size, ids: Array.from(selectedStudentIds) };
  document.getElementById("modal-delete-title").textContent = "Excluir Alunos Selecionados";
  document.getElementById("modal-delete-desc").textContent = `Tem certeza de que deseja excluir os ${selectedStudentIds.size} alunos selecionados? Esta ação não pode ser desfeita.`;
  document.getElementById("modal-student-delete").classList.remove("hidden");
}

function closeDeleteStudentModal() {
  document.getElementById("modal-student-delete").classList.add("hidden");
  studentDeleteTarget = null;
}

async function executeDeleteStudent() {
  if (!studentDeleteTarget) return;
  const btn = document.getElementById("modal-delete-confirm-btn");
  btn.disabled = true;

  try {
    if (studentDeleteTarget.mode === "single") {
      const res = await api(`/api/students/${studentDeleteTarget.id}`, { method: "DELETE" });
      const data = await res.json();
      if (res.ok && data.success) {
        selectedStudentIds.delete(studentDeleteTarget.id);
        showToast("Aluno Removido", "O cadastro do aluno foi excluído com sucesso.", "info");
      } else {
        showToast("Erro", data.error || "Falha ao excluir aluno.", "error");
      }
    } else if (studentDeleteTarget.mode === "bulk") {
      const res = await api("/api/students/bulk-delete", { method: "POST", ...jsonBody({ ids: studentDeleteTarget.ids }) });
      const data = await res.json();
      if (res.ok && data.success) {
        selectedStudentIds.clear();
        showToast("Alunos Removidos", data.message || "Alunos excluídos com sucesso.", "info");
      } else {
        showToast("Erro", data.error || "Falha ao excluir alunos.", "error");
      }
    }
    closeDeleteStudentModal();
    await loadStudents();
  } catch (e) {
    showToast("Erro", "Falha de comunicação com o servidor.", "error");
  } finally {
    btn.disabled = false;
  }
}

// ==========================================
// Presença
// ==========================================
function attendanceQuery() {
  const params = new URLSearchParams();
  const start = document.getElementById("att-start").value;
  const end = document.getElementById("att-end").value;
  const q = document.getElementById("att-search").value.trim();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (q) params.set("q", q);
  const text = params.toString();
  return text ? `?${text}` : "";
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function loadAttendance() {
  if (!authToken) return;
  const startInput = document.getElementById("att-start");
  if (!startInput.value) {
    startInput.value = todayIso();
    document.getElementById("att-end").value = todayIso();
  }
  try {
    const res = await api(`/api/attendance${attendanceQuery()}`);
    const data = await res.json();
    if (res.ok && data.success) renderAttendance(data.records || []);
  } catch (e) {
    if (e.message !== "unauthorized") showToast("Erro", "Não foi possível carregar a presença.", "error");
  }
}

function renderAttendance(records) {
  const tbody = document.getElementById("attendance-table-body");
  document.getElementById("attendance-empty").classList.toggle("hidden", records.length > 0);
  tbody.innerHTML = records.map(r => `
    <tr class="hover:bg-slate-700/30 border-b border-slate-700/40">
      <td class="py-2.5 px-4 font-mono text-indigo-300">${escapeHtml(r.matricula)}</td>
      <td class="py-2.5 px-4 text-white">${escapeHtml(r.student_name)}</td>
      <td class="py-2.5 px-4">${escapeHtml(r.turma) || "-"}</td>
      <td class="py-2.5 px-4">${escapeHtml(r.hostname)}</td>
      <td class="py-2.5 px-4 text-xs">${escapeHtml(r.login_at)}</td>
      <td class="py-2.5 px-4 text-xs">${escapeHtml(r.logout_at) || '<span class="text-emerald-400">em uso</span>'}</td>
      <td class="py-2.5 px-4 text-xs">${formatDuration(r.login_at, r.logout_at)}</td>
    </tr>
  `).join("");
}

async function downloadCsv(path, filename) {
  try {
    const res = await api(path);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    downloadBlob(await res.blob(), filename);
  } catch (e) {
    if (e.message !== "unauthorized") showToast("Erro", "Não foi possível baixar o arquivo.", "error");
  }
}

function downloadBlob(blob, filename) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revogar na hora pode cancelar o download em alguns navegadores.
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
}

// ==========================================
// Utilitários de rede / interface
// ==========================================
const BLANK_IMG = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
let maxUploadMb = 0;

function uploadWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Authorization", `Bearer ${authToken}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) {}
      resolve({ status: xhr.status, data });
    };
    xhr.onerror = () => reject(new Error("network"));
    xhr.send(formData);
  });
}

function setConnectionBadge(online) {
  const badge = document.getElementById("grid-status-badge");
  if (!badge) return;
  badge.textContent = online ? "Atualização em tempo real" : "⚠️ Sem conexão com o servidor — reconectando...";
  badge.className = online ? "text-xs text-slate-400" : "text-xs font-semibold text-amber-400";
}

async function loadServerInfo() {
  try {
    const res = await api("/api/server-info");
    const data = await res.json();
    maxUploadMb = data.max_upload_mb || 0;
  } catch (e) { /* não crítico */ }
}

// Esc fecha o modal que está por cima (os de maior z-index primeiro).
const MODAL_CLOSERS = [
  ["modal-temp-password", () => closeTempPassword()],
  ["modal-user", () => closeUserModal()],
  ["modal-student-delete", () => closeDeleteStudentModal()],
  ["modal-student-form", () => closeStudentModal()],
  ["modal-settings", () => closeSettingsModal()],
  ["modal-import", () => closeImportModal()],
  ["modal-url", () => closeUrlModal()],
  ["modal-lock", () => closeLockModal()],
  ["modal-file", () => closeFileModal()],
  ["modal-msg", () => closeMsgModal()],
  ["modal-screen", () => closeScreenModal()],
];

function closeTopModal() {
  for (const [id, close] of MODAL_CLOSERS) {
    const el = document.getElementById(id);
    if (el && !el.classList.contains("hidden")) {
      close();
      return;
    }
  }
}

function formatDuration(loginAt, logoutAt) {
  const parse = (s) => (s ? new Date(s.replace(" ", "T")) : new Date());
  const start = parse(loginAt);
  const end = parse(logoutAt);
  if (isNaN(start) || isNaN(end)) return "-";
  const minutes = Math.max(0, Math.round((end - start) / 60000));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
}

// ==========================================
// Abrir site nos computadores
// ==========================================
let currentUrlTarget = "all";

function openUrlModal(targetId, targetName) {
  currentUrlTarget = targetId;
  document.getElementById("modal-url-target-title").textContent = `Abrir Site em: ${targetName}`;
  const input = document.getElementById("modal-url-input");
  input.value = "";
  document.getElementById("modal-url").classList.remove("hidden");
  input.focus();
}

function closeUrlModal() {
  document.getElementById("modal-url").classList.add("hidden");
}

function normalizeUrl(raw) {
  let url = raw.trim();
  if (!url) return null;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(url)) url = `https://${url}`;
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) return null;
    return parsed.href;
  } catch (e) {
    return null;
  }
}

function submitOpenUrl(event) {
  event.preventDefault();
  const url = normalizeUrl(document.getElementById("modal-url-input").value);
  if (!url) {
    alert("Digite um endereço válido, ex.: www.google.com");
    return;
  }
  sendCommand({ action: "open_url", target: currentUrlTarget, url });
  closeUrlModal();
  showToast("Site Enviado", url, "success");
}

function zoomOpenUrl() {
  if (!currentZoomId) return;
  const client = clientsMap.get(currentZoomId);
  openUrlModal(currentZoomId, client ? client.info.hostname : currentZoomId);
}

// ==========================================
// Bloquear sala com mensagem personalizada
// ==========================================
const DEFAULT_LOCK_MESSAGE = "Atenção na explicação do professor.";

function openLockModal() {
  document.getElementById("modal-lock-title").textContent = `🔒 Bloquear: ${groupLabel()}`;
  document.getElementById("modal-lock-duration").value = "0";
  const input = document.getElementById("modal-lock-message");
  input.value = DEFAULT_LOCK_MESSAGE;
  document.getElementById("modal-lock").classList.remove("hidden");
  input.select();
}

function closeLockModal() {
  document.getElementById("modal-lock").classList.add("hidden");
}

function submitLockAll(event) {
  event.preventDefault();
  const message = document.getElementById("modal-lock-message").value.trim() || DEFAULT_LOCK_MESSAGE;
  const duration = parseInt(document.getElementById("modal-lock-duration").value, 10) || 0;
  sendCommand({ action: "lock", target: groupTarget(), message, duration });
  if (duration) showToast("Bloqueio com timer", `${groupLabel()}: libera sozinho em ${duration / 60} min.`, "info");
  closeLockModal();
}

document.getElementById("lock-presets").addEventListener("click", (e) => {
  const preset = e.target.closest("[data-preset]");
  if (preset) document.getElementById("modal-lock-message").value = preset.dataset.preset;
});

// ==========================================
// Salvar print da tela do aluno
// ==========================================
function saveSnapshot() {
  const client = currentZoomId && clientsMap.get(currentZoomId);
  if (!client || !client.latest_frame) {
    showToast("Sem imagem", "Ainda não chegou nenhuma imagem deste computador.", "warning");
    return;
  }
  const d = new Date();
  const stamp = `${todayIso()}_${String(d.getHours()).padStart(2, "0")}-${String(d.getMinutes()).padStart(2, "0")}-${String(d.getSeconds()).padStart(2, "0")}`;
  const name = `${client.info.hostname}_${client.info.student_name || "sem-aluno"}_${stamp}.jpg`.replace(/[\\/:*?"<>|\s]+/g, "_");
  fetch(client.latest_frame).then(r => r.blob()).then(blob => downloadBlob(blob, name));
}

// ==========================================
// Configurações: troca da senha do painel
// ==========================================
function openSettingsModal(forced = false) {
  forcedPasswordChange = forced;
  ["settings-current", "settings-new", "settings-confirm"].forEach(id => { document.getElementById(id).value = ""; });
  document.getElementById("settings-error").classList.add("hidden");
  document.getElementById("settings-title").textContent = forced ? "🔑 Crie sua senha" : "⚙️ Minha Senha";
  document.getElementById("settings-note").textContent = forced
    ? "Você entrou com uma senha provisória. Para continuar, crie uma senha só sua (digite a provisória no primeiro campo)."
    : "Trocar a senha encerra as sessões abertas em outros navegadores.";
  document.getElementById("settings-cancel").classList.toggle("hidden", forced);
  document.getElementById("settings-close-x").classList.toggle("hidden", forced);
  document.getElementById("modal-settings").classList.remove("hidden");
  document.getElementById("settings-current").focus();
}

function closeSettingsModal() {
  if (forcedPasswordChange) return;   // a troca da senha provisória é obrigatória
  document.getElementById("modal-settings").classList.add("hidden");
}

async function submitChangePassword(event) {
  event.preventDefault();
  const current = document.getElementById("settings-current").value;
  const next = document.getElementById("settings-new").value;
  const confirmNext = document.getElementById("settings-confirm").value;
  const errorBox = document.getElementById("settings-error");
  const showError = (msg) => { errorBox.textContent = msg; errorBox.classList.remove("hidden"); };

  if (next !== confirmNext) return showError("As duas novas senhas não são iguais.");
  if (next.trim().length < 8) return showError("A nova senha precisa ter pelo menos 8 caracteres.");

  const btn = document.getElementById("settings-save-btn");
  btn.disabled = true;
  try {
    const res = await api("/api/me/password", {
      method: "POST", ...jsonBody({ current_password: current, new_password: next })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const wasForced = forcedPasswordChange;
      forcedPasswordChange = false;
      authToken = data.token;
      currentUser = data.user;
      saveToken(authToken, !sessionStorage.getItem(AUTH_TOKEN_KEY));
      document.getElementById("modal-settings").classList.add("hidden");
      applyUserUI();
      showToast("Senha alterada", "A nova senha já está valendo.", "success");
      // Se já havia painel aberto, o servidor o fecha e ele reconecta sozinho com o token novo.
      if (wasForced) connectWebSocket();
    } else {
      showError(data.error || data.detail || "Não foi possível alterar a senha.");
    }
  } catch (e) {
    if (e.message !== "unauthorized") showError("Erro de conexão com o servidor.");
  } finally {
    btn.disabled = false;
  }
}

// ==========================================
// Importação de alunos por planilha
// ==========================================
function openImportModal() {
  document.getElementById("import-file-input").value = "";
  document.getElementById("import-update-existing").checked = false;
  document.getElementById("import-result").classList.add("hidden");
  document.getElementById("modal-import").classList.remove("hidden");
}

function closeImportModal() {
  document.getElementById("modal-import").classList.add("hidden");
}

async function submitImportStudents(event) {
  event.preventDefault();
  const fileInput = document.getElementById("import-file-input");
  if (!fileInput.files.length) return;
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("update_existing", document.getElementById("import-update-existing").checked ? "true" : "false");

  const btn = document.getElementById("import-submit-btn");
  const box = document.getElementById("import-result");
  btn.disabled = true;
  btn.textContent = "Importando...";
  box.className = "text-xs rounded-xl p-3 max-h-40 overflow-y-auto bg-slate-900 border border-slate-700 text-slate-300";
  box.textContent = "Processando a planilha (pode levar alguns segundos)...";

  try {
    const res = await api("/api/students/import", { method: "POST", body: formData });
    const data = await res.json();
    box.innerHTML = "";
    if (res.ok && data.success) {
      const summary = document.createElement("div");
      summary.className = "font-semibold text-emerald-300 mb-1";
      summary.textContent = `✔ ${data.created} cadastrado(s), ${data.updated} atualizado(s), ${data.errors.length} aviso(s).`;
      box.appendChild(summary);
      data.errors.slice(0, 200).forEach(msg => {
        const line = document.createElement("div");
        line.className = "text-amber-300";
        line.textContent = msg;
        box.appendChild(line);
      });
      fileInput.value = "";
      await loadStudents(document.getElementById("students-search-input").value || "");
    } else {
      box.className = "text-xs rounded-xl p-3 bg-red-950/60 border border-red-500/30 text-red-300";
      box.textContent = data.error || "Falha ao importar.";
    }
  } catch (e) {
    if (e.message !== "unauthorized") box.textContent = "Erro de conexão com o servidor.";
  } finally {
    btn.disabled = false;
    btn.textContent = "Importar";
  }
}

// ==========================================
// Turmas: filtro da grade e alvo dos botões do topo
// ==========================================
let groupFilter = "";

function groupTarget() {
  return groupFilter ? `turma:${groupFilter}` : "all";
}

function groupLabel() {
  return groupFilter ? `Turma ${groupFilter}` : "Toda a Sala";
}

function setGroupFilter(value) {
  groupFilter = value || "";
  const label = document.getElementById("group-target-label");
  label.textContent = `Botões do topo agem só na Turma ${groupFilter}`;
  label.classList.toggle("hidden", !groupFilter);
  renderGrid();
}

function updateTurmaOptions() {
  const select = document.getElementById("turma-filter");
  if (!select) return;
  const turmas = new Set();
  clientsMap.forEach(c => { if (c.info.turma) turmas.add(c.info.turma.trim()); });
  if (groupFilter) turmas.add(groupFilter);   // mantém a escolha mesmo se a turma sair
  const sorted = Array.from(turmas).sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true }));
  const key = sorted.join("\u0000");
  if (select.dataset.key === key) return;
  select.dataset.key = key;
  select.innerHTML = "";
  select.appendChild(new Option("Toda a sala", ""));
  sorted.forEach(t => select.appendChild(new Option(t, t)));
  select.value = groupFilter;
}

// ==========================================
// Timer de bloqueio: contagem regressiva nos cartões
// ==========================================
function setLockDeadline(info, remainingSeconds) {
  info.lock_deadline = remainingSeconds > 0 ? Date.now() + remainingSeconds * 1000 : null;
}

function lockCountdownText(info) {
  if (!info.is_locked || !info.lock_deadline) return "";
  const left = Math.max(0, Math.ceil((info.lock_deadline - Date.now()) / 1000));
  return `libera em ${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
}

setInterval(() => {
  clientsMap.forEach(c => {
    if (!c.info.lock_deadline) return;
    const el = document.getElementById(`countdown-${c.info.id}`);
    if (el) el.textContent = lockCountdownText(c.info);
  });
}, 1000);

// ==========================================
// Regras: programas e sites bloqueados
// ==========================================
function linesOf(id) {
  return document.getElementById(id).value.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
}

function updateRulesDot(enabled) {
  const dot = document.getElementById("rules-status-dot");
  if (!dot) return;
  dot.className = `w-2 h-2 rounded-full ${enabled ? "bg-emerald-400" : "bg-slate-600"}`;
  dot.title = enabled ? "Regras ativas" : "Regras desativadas";
}

function fillRules(data) {
  document.getElementById("rules-enabled").checked = !!data.enabled;
  document.getElementById("rules-programs").value = (data.programs || []).join("\n");
  document.getElementById("rules-sites").value = (data.sites || []).join("\n");
  updateRulesDot(data.enabled);
}

async function loadRules() {
  try {
    const res = await api("/api/rules");
    const data = await res.json();
    if (res.ok && data.success) fillRules(data);
  } catch (e) { /* não crítico */ }
}

async function saveRules() {
  const btn = document.getElementById("rules-save-btn");
  const status = document.getElementById("rules-save-status");
  btn.disabled = true;
  status.textContent = "Salvando...";
  try {
    const payload = {
      enabled: document.getElementById("rules-enabled").checked,
      programs: linesOf("rules-programs"),
      sites: linesOf("rules-sites"),
    };
    const res = await api("/api/rules", { method: "PUT", ...jsonBody(payload) });
    const data = await res.json();
    if (res.ok && data.success) {
      fillRules(data);   // mostra a lista já normalizada (ex.: "youtube.com" vira "youtube")
      status.textContent = `Aplicado em ${data.sent_count} computador(es) conectado(s).`;
      showToast("Regras salvas", data.enabled ? "Bloqueios ativos nos computadores." : "Regras desativadas.", "success");
    } else {
      status.textContent = data.error || "Erro ao salvar.";
    }
  } catch (e) {
    if (e.message !== "unauthorized") status.textContent = "Erro de conexão com o servidor.";
  } finally {
    btn.disabled = false;
  }
}

document.querySelectorAll("[data-rules-target]").forEach(group => {
  group.addEventListener("click", (e) => {
    const chip = e.target.closest("[data-add]");
    if (!chip) return;
    const area = document.getElementById(group.dataset.rulesTarget);
    const items = linesOf(area.id);
    if (!items.some(i => i.toLowerCase() === chip.dataset.add.toLowerCase())) items.push(chip.dataset.add);
    area.value = items.join("\n");
  });
});

async function loadEvents() {
  try {
    const res = await api("/api/events");
    const data = await res.json();
    if (!res.ok || !data.success) return;
    const events = data.events || [];
    document.getElementById("events-empty").classList.toggle("hidden", events.length > 0);
    document.getElementById("events-table-body").innerHTML = events.map(ev => `
      <tr class="hover:bg-slate-700/30">
        <td class="py-2 px-4 text-xs">${escapeHtml(ev.at)}</td>
        <td class="py-2 px-4">${escapeHtml(ev.hostname)}</td>
        <td class="py-2 px-4">${escapeHtml(ev.student_name) || "-"}</td>
        <td class="py-2 px-4 text-xs">${ev.kind === "site" ? "🌐 Site" : "🚫 Programa"}</td>
        <td class="py-2 px-4 font-mono text-xs text-amber-300">${escapeHtml(ev.detail)}</td>
      </tr>`).join("");
  } catch (e) { /* não crítico */ }
}

// ==========================================
// Sessão e perfil do usuário logado
// ==========================================
const ROLE_LABELS = { admin: "Administrador", operador: "Operador" };

function startSession(token, user) {
  authToken = token;
  currentUser = user || null;
  applyUserUI();
  showAppScreen();
  if (user && user.must_change) {
    openSettingsModal(true);   // sem trocar a senha provisória não há painel
    return;
  }
  connectWebSocket();
}

function applyUserUI() {
  const user = currentUser;
  const isAdmin = !!user && user.role === "admin";
  document.body.classList.toggle("role-operador", !!user && !isAdmin);
  document.getElementById("user-name").textContent = user ? user.name : "";
  document.getElementById("user-role").textContent = user ? `${ROLE_LABELS[user.role] || user.role} · ${user.email}` : "";
  document.querySelectorAll("[data-admin-only]").forEach(el => { el.style.display = isAdmin || !user ? "" : "none"; });
  ["rules-enabled", "rules-programs", "rules-sites"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!user && !isAdmin;
  });
}

// ==========================================
// Equipe: contas, senhas provisórias e registro de ações
// ==========================================
let teamUsers = [];

function formatDate(value) {
  return value ? escapeHtml(value) : '<span class="text-slate-500">nunca</span>';
}

async function loadUsers() {
  try {
    const res = await api("/api/users");
    const data = await res.json();
    if (!res.ok || !data.success) return;
    teamUsers = data.users;
    document.getElementById("users-table-body").innerHTML = teamUsers.map(u => {
      const isMe = currentUser && u.id === currentUser.id;
      const status = !u.active
        ? '<span class="text-red-400">Desativada</span>'
        : u.must_change ? '<span class="text-amber-300">Aguardando 1º acesso</span>' : '<span class="text-emerald-400">Ativa</span>';
      const btn = "text-[11px] px-2 py-1 rounded-lg border border-slate-600 text-slate-200 hover:bg-slate-700";
      return `
        <tr class="hover:bg-slate-700/30" data-user-id="${u.id}">
          <td class="py-2.5 px-4 font-medium text-white">${escapeHtml(u.name)}${isMe ? ' <span class="text-[10px] text-indigo-300">(você)</span>' : ""}</td>
          <td class="py-2.5 px-4 font-mono text-xs">${escapeHtml(u.email)}</td>
          <td class="py-2.5 px-4 text-xs">${escapeHtml(ROLE_LABELS[u.role] || u.role)}</td>
          <td class="py-2.5 px-4 text-xs">${status}</td>
          <td class="py-2.5 px-4 text-xs">${formatDate(u.last_login)}</td>
          <td class="py-2.5 px-4 text-right whitespace-nowrap space-x-1">
            <button data-user-action="reset" class="${btn}">Nova senha</button>
            ${isMe ? "" : `<button data-user-action="role" class="${btn}">${u.role === "admin" ? "Tornar operador" : "Tornar admin"}</button>
            <button data-user-action="active" class="${btn}">${u.active ? "Desativar" : "Ativar"}</button>
            <button data-user-action="delete" class="${btn} hover:text-red-300">Excluir</button>`}
          </td>
        </tr>`;
    }).join("");
  } catch (e) { /* não crítico */ }
}

document.getElementById("users-table-body").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-user-action]");
  const row = btn && btn.closest("[data-user-id]");
  if (!row) return;
  const user = teamUsers.find(u => u.id === Number(row.dataset.userId));
  if (!user) return;
  try {
    switch (btn.dataset.userAction) {
      case "reset": {
        if (!confirm(`Gerar uma nova senha provisória para ${user.name}? A senha atual deixa de funcionar.`)) return;
        const res = await api(`/api/users/${user.id}/reset-password`, { method: "POST" });
        const data = await res.json();
        if (res.ok && data.success) { showTempPassword(user.email, data.temp_password); loadUsers(); }
        else showToast("Erro", data.error || "Não foi possível redefinir.", "error");
        break;
      }
      case "role":
      case "active": {
        const role = btn.dataset.userAction === "role" ? (user.role === "admin" ? "operador" : "admin") : user.role;
        const active = btn.dataset.userAction === "active" ? !user.active : user.active;
        const res = await api(`/api/users/${user.id}`, { method: "PUT", ...jsonBody({ name: user.name, role, active }) });
        const data = await res.json();
        if (!(res.ok && data.success)) showToast("Erro", data.error || "Não foi possível alterar.", "error");
        loadUsers();
        break;
      }
      case "delete": {
        if (!confirm(`Excluir a conta de ${user.name}? Isto não pode ser desfeito.`)) return;
        const res = await api(`/api/users/${user.id}`, { method: "DELETE" });
        const data = await res.json();
        if (!(res.ok && data.success)) showToast("Erro", data.error || "Não foi possível excluir.", "error");
        loadUsers();
        break;
      }
    }
  } catch (err) {
    if (err.message !== "unauthorized") showToast("Erro", "Falha de comunicação com o servidor.", "error");
  }
});

function openUserModal() {
  ["user-form-name", "user-form-email"].forEach(id => { document.getElementById(id).value = ""; });
  document.getElementById("user-form-role").value = "admin";
  document.getElementById("user-form-error").classList.add("hidden");
  document.getElementById("modal-user").classList.remove("hidden");
  document.getElementById("user-form-name").focus();
}

function closeUserModal() {
  document.getElementById("modal-user").classList.add("hidden");
}

async function submitCreateUser(event) {
  event.preventDefault();
  const payload = {
    name: document.getElementById("user-form-name").value.trim(),
    email: document.getElementById("user-form-email").value.trim(),
    role: document.getElementById("user-form-role").value,
  };
  const errorBox = document.getElementById("user-form-error");
  const btn = document.getElementById("user-form-save");
  btn.disabled = true;
  try {
    const res = await api("/api/users", { method: "POST", ...jsonBody(payload) });
    const data = await res.json();
    if (res.ok && data.success) {
      closeUserModal();
      showTempPassword(data.user.email, data.user.temp_password);
      loadUsers();
    } else {
      errorBox.textContent = data.error || "Não foi possível criar a conta.";
      errorBox.classList.remove("hidden");
    }
  } catch (e) {
    if (e.message !== "unauthorized") {
      errorBox.textContent = "Erro de conexão com o servidor.";
      errorBox.classList.remove("hidden");
    }
  } finally {
    btn.disabled = false;
  }
}

function showTempPassword(email, password) {
  document.getElementById("temp-pass-email").textContent = email;
  document.getElementById("temp-pass-value").value = password;
  document.getElementById("modal-temp-password").classList.remove("hidden");
}

function closeTempPassword() {
  document.getElementById("temp-pass-value").value = "";   // não deixa a senha na tela
  document.getElementById("modal-temp-password").classList.add("hidden");
}

async function copyTempPassword() {
  const input = document.getElementById("temp-pass-value");
  try {
    await navigator.clipboard.writeText(input.value);
  } catch (e) {
    input.select();
    document.execCommand("copy");
  }
  showToast("Copiada", "Senha provisória copiada.", "success");
}

async function loadAudit() {
  try {
    const res = await api("/api/audit");
    const data = await res.json();
    if (!res.ok || !data.success) return;
    document.getElementById("audit-table-body").innerHTML = data.records.map(r => `
      <tr class="hover:bg-slate-700/30">
        <td class="py-2 px-4 text-xs whitespace-nowrap">${escapeHtml(r.at)}</td>
        <td class="py-2 px-4 text-xs">${escapeHtml(r.user_name || r.user_email)}</td>
        <td class="py-2 px-4 text-xs">${escapeHtml(r.action)}</td>
        <td class="py-2 px-4 text-xs text-slate-400">${escapeHtml(r.detail)}</td>
      </tr>`).join("");
  } catch (e) { /* não crítico */ }
}

// Inicia verificação de autenticação ao carregar a página
checkSavedAuth();
