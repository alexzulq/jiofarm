// JioFarm Web Control Center — Vanilla JavaScript Application
(function () {
  'use strict';

  // State Management
  const state = {
    telemetry: null,
    logs: [],
    links: [],
    hunts: [],
    config: null,
    activeTab: 'overview',
    autoScrollLogs: true,
    ws: null,
    wsConnected: false,
    elapsedTimer: null,
    pollInterval: null,
  };

  // DOM Elements
  const el = {
    statusBadge: document.getElementById('status-badge'),
    statusText: document.getElementById('status-text'),
    balanceVal: document.getElementById('balance-val'),
    balanceProvider: document.getElementById('balance-provider'),
    btnRefreshBal: document.getElementById('btn-refresh-balance'),
    elapsedVal: document.getElementById('elapsed-val'),
    kpiLinks: document.getElementById('kpi-links'),
    kpiWorkers: document.getElementById('kpi-workers'),
    kpiAttempts: document.getElementById('kpi-attempts'),
    kpiRefunds: document.getElementById('kpi-refunds'),
    btnStart: document.getElementById('btn-start-hunt'),
    btnStop: document.getElementById('btn-stop-hunt'),
    workersGrid: document.getElementById('workers-grid'),
    workersCountBadge: document.getElementById('workers-count-badge'),
    linksTableBody: document.getElementById('links-table-body'),
    linksCountBadge: document.getElementById('links-count-badge'),
    terminalLogs: document.getElementById('terminal-logs'),
    searchLinks: document.getElementById('search-links'),
    toastContainer: document.getElementById('toast-container'),
    configWarningBanner: document.getElementById('config-warning-banner'),
  };

  // Initialize
  document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupControls();
    setupSettings();
    initWebSocket();
    fetchInitialData();

    // Start 1s timer for elapsed time
    state.elapsedTimer = setInterval(updateElapsedClock, 1000);
  });

  // Navigation / Tabs
  function setupNavigation() {
    const tabs = document.querySelectorAll('.nav-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const target = tab.dataset.tab;
        switchTab(target);
      });
    });
  }

  function switchTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll('.nav-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.tab === tabName);
    });
    document.querySelectorAll('.tab-content').forEach(c => {
      c.style.display = (c.id === `tab-${tabName}`) ? 'block' : 'none';
    });

    if (tabName === 'vault') {
      fetchLinks();
    } else if (tabName === 'history') {
      fetchHistory();
    } else if (tabName === 'settings') {
      fetchConfig();
    }
  }

  // Setup Hunter Controls
  function setupControls() {
    // Sliders & value displays
    const concurrencySlider = document.getElementById('ctrl-concurrency');
    const concurrencyVal = document.getElementById('ctrl-concurrency-val');
    concurrencySlider?.addEventListener('input', (e) => {
      concurrencyVal.textContent = e.target.value;
    });

    const maxPriceSlider = document.getElementById('ctrl-max-price');
    const maxPriceVal = document.getElementById('ctrl-max-price-val');
    maxPriceSlider?.addEventListener('input', (e) => {
      maxPriceVal.textContent = `$${parseFloat(e.target.value).toFixed(2)}`;
    });

    // Start button
    el.btnStart?.addEventListener('click', async () => {
      const concurrency = parseInt(concurrencySlider?.value || '2', 10);
      const maxPrice = parseFloat(maxPriceSlider?.value || '1.0');
      const targetMode = document.querySelector('input[name="target-mode"]:checked')?.value || 'unlimited';
      
      let target = null;
      let durationMinutes = null;
      let count = null;

      if (targetMode === 'links') {
        target = parseInt(document.getElementById('target-links-input')?.value || '3', 10);
      } else if (targetMode === 'duration') {
        durationMinutes = parseInt(document.getElementById('target-duration-input')?.value || '60', 10);
      } else if (targetMode === 'count') {
        count = parseInt(document.getElementById('target-count-input')?.value || '5', 10);
      }

      try {
        el.btnStart.disabled = true;
        el.btnStart.textContent = 'Memulai...';
        const res = await fetch('/api/hunter/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: jsonStringify({
            concurrency,
            max_price: maxPrice,
            target,
            duration_minutes: durationMinutes,
            count
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Gagal memulai hunter');
        showToast('🚀 Hunter berhasil dimulai!', 'success');
        updateUI(data);
      } catch (err) {
        showToast(err.message, 'error');
      } finally {
        el.btnStart.disabled = false;
        el.btnStart.innerHTML = '<span>🚀</span> Mulai Perburuan';
      }
    });

    // Stop button
    el.btnStop?.addEventListener('click', async () => {
      try {
        el.btnStop.disabled = true;
        el.btnStop.textContent = 'Menghentikan...';
        const res = await fetch('/api/hunter/stop', { method: 'POST' });
        const data = await res.json();
        showToast('🛑 Permintaan stop dikirim ke worker', 'warning');
        updateUI(data);
      } catch (err) {
        showToast(err.message, 'error');
      } finally {
        el.btnStop.disabled = false;
        el.btnStop.innerHTML = '<span>🛑</span> Stop Hunter';
      }
    });

    // Balance refresh
    el.btnRefreshBal?.addEventListener('click', async () => {
      try {
        el.btnRefreshBal.style.transform = 'rotate(360deg)';
        const res = await fetch('/api/balance/refresh');
        const data = await res.json();
        const isSplit = (data.provider === 'split' || data.provider === 'both' || data.provider === 'dual');
        if (isSplit && data.balances) {
          const gStr = data.balances.grizzly !== null ? `$${parseFloat(data.balances.grizzly).toFixed(2)}` : '—';
          const fStr = data.balances.fivesim !== null ? `$${parseFloat(data.balances.fivesim).toFixed(2)}` : '—';
          el.balanceVal.innerHTML = `<span title="GrizzlySMS">🐻 ${gStr}</span> <span style="opacity:0.4">|</span> <span title="5SIM">⚡ ${fStr}</span>`;
          el.balanceProvider.textContent = 'DUAL';
          showToast(`Saldo: Grizzly ${gStr} | 5SIM ${fStr}`, 'success');
        } else if (data.balance !== null && data.balance !== undefined) {
          el.balanceVal.textContent = `$${parseFloat(data.balance).toFixed(2)}`;
          el.balanceProvider.textContent = data.provider.toUpperCase();
          showToast(`Saldo ${data.provider}: $${data.balance.toFixed(2)}`, 'success');
        } else if (data.error) {
          showToast(`Cek Saldo: ${data.error}`, 'error');
        }
      } catch (err) {
        showToast('Gagal refresh saldo', 'error');
      } finally {
        setTimeout(() => { el.btnRefreshBal.style.transform = ''; }, 300);
      }
    });

    // Search in Links Vault
    el.searchLinks?.addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase();
      const rows = document.querySelectorAll('.vault-row');
      rows.forEach(r => {
        const text = r.textContent.toLowerCase();
        r.style.display = text.includes(q) ? '' : 'none';
      });
    });

    // Clear Terminal Logs
    document.getElementById('btn-clear-logs')?.addEventListener('click', () => {
      state.logs = [];
      if (el.terminalLogs) el.terminalLogs.innerHTML = '';
      showToast('Log terminal dibersihkan', 'info');
    });

    // Auto-scroll toggle
    const chkAutoScroll = document.getElementById('chk-autoscroll');
    chkAutoScroll?.addEventListener('change', (e) => {
      state.autoScrollLogs = e.target.checked;
    });

    // Mode Radio changes
    document.querySelectorAll('input[name="target-mode"]').forEach(radio => {
      radio.addEventListener('change', (e) => {
        document.querySelectorAll('.mode-options').forEach(opt => opt.style.display = 'none');
        const optEl = document.getElementById(`opt-${e.target.value}`);
        if (optEl) optEl.style.display = 'block';
      });
    });
  }

  // Settings Configuration Form
  function setupSettings() {
    const form = document.getElementById('settings-form');
    form?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const provider = document.getElementById('setting-provider').value;
      const grizzly_api_key = document.getElementById('setting-grizzly-key').value;
      const fivesim_api_key = document.getElementById('setting-fivesim-key').value;
      const max_price = parseFloat(document.getElementById('setting-max-price').value || '1.0');
      const concurrency = parseInt(document.getElementById('setting-concurrency').value || '2', 10);
      const cancel_delay_seconds = parseFloat(document.getElementById('setting-cancel-delay').value || '150');
      const otp_fail_delay_seconds = parseFloat(document.getElementById('setting-otp-fail-delay').value || '420');
      const tg_bot_token = document.getElementById('setting-tg-token').value;
      const tg_chat_id = document.getElementById('setting-tg-chat').value;

      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: jsonStringify({
            provider,
            grizzly_api_key,
            fivesim_api_key,
            max_price,
            concurrency,
            cancel_delay_seconds,
            otp_fail_delay_seconds,
            tg_bot_token,
            tg_chat_id,
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan pengaturan');
        showToast('✅ Pengaturan berhasil disimpan ke .env!', 'success');
        fetchInitialData();
      } catch (err) {
        showToast(err.message, 'error');
      }
    });

    // Provider select switcher in settings
    document.getElementById('setting-provider')?.addEventListener('change', (e) => {
      const val = e.target.value;
      const showGrizzly = (val === 'grizzlysms' || val === 'split');
      const showFiveSim = (val === 'fivesim' || val === 'split');
      document.getElementById('group-grizzly').style.display = showGrizzly ? 'block' : 'none';
      document.getElementById('group-fivesim').style.display = showFiveSim ? 'block' : 'none';
    });

    // Test Telegram button
    document.getElementById('btn-test-tg')?.addEventListener('click', async () => {
      const bot_token = document.getElementById('setting-tg-token').value;
      const chat_id = document.getElementById('setting-tg-chat').value;
      if (!bot_token || !chat_id) {
        showToast('Masukkan Bot Token dan Chat ID terlebih dahulu', 'warning');
        return;
      }
      try {
        showToast('Mengirim pesan tes ke Telegram...', 'info');
        const res = await fetch('/api/test-telegram', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: jsonStringify({ bot_token, chat_id })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Gagal mengirim');
        showToast('✅ Pesan berhasil diterima di Telegram!', 'success');
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  // Initial Data Fetch
  async function fetchInitialData() {
    try {
      const res = await fetch('/api/telemetry');
      const data = await res.json();
      updateUI(data);

      const logRes = await fetch('/api/logs');
      const logs = await logRes.json();
      renderLogs(logs);

      fetchLinks();
    } catch (err) {
      console.warn('Initial telemetry fetch failed', err);
    }
  }

  // WebSocket Setup
  function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
      state.ws = new WebSocket(wsUrl);

      state.ws.onopen = () => {
        state.wsConnected = true;
        clearInterval(state.pollInterval);
        state.pollInterval = null;
      };

      state.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'init') {
            updateUI(msg.state);
            renderLogs(msg.logs);
          } else if (msg.type === 'state') {
            updateUI(msg.data);
          } else if (msg.type === 'log') {
            appendLog(msg.data);
          }
        } catch (e) {
          console.error('WS parse error', e);
        }
      };

      state.ws.onclose = () => {
        state.wsConnected = false;
        // Fallback to HTTP polling if WS disconnects
        if (!state.pollInterval) {
          state.pollInterval = setInterval(fetchInitialData, 2000);
        }
        setTimeout(initWebSocket, 3000);
      };

      state.ws.onerror = () => {
        state.ws?.close();
      };
    } catch (e) {
      // Polling fallback
      if (!state.pollInterval) {
        state.pollInterval = setInterval(fetchInitialData, 2000);
      }
    }
  }

  // UI Updates
  function updateUI(t) {
    if (!t) return;
    state.telemetry = t;

    // Status Badge
    const isRunning = (t.status === 'running');
    const isStopping = (t.status === 'stopping');
    el.statusBadge.className = `status-pill ${t.status}`;
    el.statusText.textContent = isRunning ? 'Running' : (isStopping ? 'Stopping...' : 'Idle');

    // Action buttons state
    if (el.btnStart) el.btnStart.style.display = isRunning ? 'none' : 'inline-flex';
    if (el.btnStop) el.btnStop.style.display = isRunning ? 'inline-flex' : 'none';

    // Warning Banner if not configured
    if (el.configWarningBanner) {
      el.configWarningBanner.style.display = t.is_configured ? 'none' : 'flex';
    }

    // Balance
    const isSplit = (t.provider === 'split' || t.provider === 'both' || t.provider === 'dual');
    if (isSplit && t.balances) {
      el.balanceProvider.textContent = 'DUAL';
      const gStr = t.balances.grizzly !== null ? `$${parseFloat(t.balances.grizzly).toFixed(2)}` : '—';
      const fStr = t.balances.fivesim !== null ? `$${parseFloat(t.balances.fivesim).toFixed(2)}` : '—';
      el.balanceVal.innerHTML = `<span title="GrizzlySMS">🐻 ${gStr}</span> <span style="opacity:0.4">|</span> <span title="5SIM">⚡ ${fStr}</span>`;
    } else if (t.balance !== null && t.balance !== undefined) {
      el.balanceVal.textContent = `$${parseFloat(t.balance).toFixed(2)}`;
      el.balanceProvider.textContent = (t.provider || 'GrizzlySMS').toUpperCase();
    } else {
      el.balanceVal.textContent = t.is_configured ? '$0.00' : 'No Key';
      el.balanceProvider.textContent = (t.provider || 'GrizzlySMS').toUpperCase();
    }

    // KPIs
    if (el.kpiLinks) el.kpiLinks.textContent = t.current_found !== undefined ? t.current_found : 0;
    const activeWorkers = (t.workers || []).filter(w => w.phase !== 'IDLE' && w.phase !== 'DONE' && w.phase !== 'ERROR').length;
    if (el.kpiWorkers) el.kpiWorkers.textContent = `${activeWorkers} / ${t.concurrency || 2}`;
    if (el.kpiAttempts) el.kpiAttempts.textContent = t.done_count || 0;
    if (el.kpiRefunds) el.kpiRefunds.textContent = t.refunds_pending || 0;

    // Render Worker Cards
    renderWorkers(t.workers || []);
  }

  // Elapsed Clock
  function updateElapsedClock() {
    if (!state.telemetry || state.telemetry.status !== 'running') {
      return;
    }
    state.telemetry.elapsed_seconds = (state.telemetry.elapsed_seconds || 0) + 1;
    const s = state.telemetry.elapsed_seconds;
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    if (el.elapsedVal) {
      el.elapsedVal.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
  }

  // Render Worker Cards
  function renderWorkers(workers) {
    if (!el.workersGrid) return;
    if (!workers || workers.length === 0) {
      el.workersGrid.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 2.5rem; text-align: center; color: var(--text-dim);" class="glass">
          <div style="font-size: 2rem; margin-bottom: 0.5rem;">💤</div>
          <div>Tidak ada worker aktif. Klik <b>Mulai Perburuan</b> untuk menjalankan worker.</div>
        </div>
      `;
      if (el.workersCountBadge) el.workersCountBadge.textContent = '0';
      return;
    }

    if (el.workersCountBadge) el.workersCountBadge.textContent = workers.length.toString();

    const phaseSteps = {
      'IDLE': 0,
      'RENTING': 1,
      'CHECKING': 2,
      'SENDING_OTP': 3,
      'WAITING_OTP': 4,
      'VALIDATING': 5,
      'HUNTING': 6,
      'DONE': 7,
      'ERROR': -1,
    };

    const phaseLabels = {
      'IDLE': 'IDLE',
      'RENTING': '📱 SEWA NOMOR',
      'CHECKING': '🔍 CEK JIO',
      'SENDING_OTP': '📤 KIRIM OTP',
      'WAITING_OTP': '⏳ MENUNGGU OTP',
      'VALIDATING': '🔐 VALIDASI',
      'HUNTING': '🎯 BERBURU LINK',
      'DONE': '✅ SELESAI',
      'ERROR': '❌ ERROR / REFUND',
    };

    el.workersGrid.innerHTML = workers.map(w => {
      const step = phaseSteps[w.phase] || 0;
      const isError = (w.phase === 'ERROR');
      const isDone = (w.phase === 'DONE');
      const isHunting = (w.phase === 'HUNTING');
      const isWaiting = (w.phase === 'WAITING_OTP');

      let cardClass = 'worker-card';
      if (isHunting) cardClass += ' hunting';
      else if (isDone) cardClass += ' done';
      else if (w.phase !== 'IDLE') cardClass += ' active';

      // Pipeline 7 steps
      let pipelineHtml = '<div class="pipeline-bar">';
      for (let i = 1; i <= 7; i++) {
        let stepClass = 'pipeline-step';
        if (isError && i === Math.abs(step)) stepClass += ' failed';
        else if (i === step) stepClass += ' active';
        else if (i < step || isDone) stepClass += ' completed';
        pipelineHtml += `<div class="${stepClass}"></div>`;
      }
      pipelineHtml += '</div>';

      return `
        <div class="${cardClass}">
          <div class="worker-header">
            <div class="worker-id">
              <span style="opacity: 0.6">Worker</span> #${w.wid}
              ${w.provider_name ? `<span class="worker-prov-tag ${w.provider_name.toLowerCase()}">${w.provider_name === 'GRIZZLY' ? '🐻' : '⚡'} ${w.provider_name}</span>` : ''}
            </div>
            <div class="phase-badge phase-${w.phase}">
              ${phaseLabels[w.phase] || w.phase}
            </div>
          </div>

          ${pipelineHtml}

          <div class="worker-info">
            <div class="worker-detail-row">
              <span class="worker-detail-label">Nomor HP:</span>
              <span class="worker-detail-val phone">${w.phone ? formatPhone(w.phone) : '—'}</span>
            </div>
            <div class="worker-detail-row">
              <span class="worker-detail-label">OTP Masuk:</span>
              <span class="worker-detail-val otp">${w.otp || '—'}</span>
            </div>
            <div class="worker-detail-row">
              <span class="worker-detail-label">Attempt:</span>
              <span class="worker-detail-val">#${w.attempts || 0}</span>
            </div>
          </div>

          ${w.link ? `
            <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); padding: 0.5rem; border-radius: var(--radius-sm); font-size: 0.78rem;">
              <span style="color: var(--accent-green); font-weight: 700;">🎯 Link Didapat!</span>
              <a href="${w.link}" target="_blank" style="color: #38bdf8; text-decoration: underline; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${w.link}</a>
            </div>
          ` : ''}

          ${w.error ? `
            <div class="worker-status-msg" style="border-left-color: ${isError ? 'var(--accent-red)' : 'var(--accent-gold)'}">
              ${escapeHtml(w.error)}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  // Render Logs
  function renderLogs(logs) {
    if (!el.terminalLogs) return;
    el.terminalLogs.innerHTML = '';
    logs.forEach(appendLog);
  }

  function appendLog(log) {
    if (!el.terminalLogs) return;
    state.logs.push(log);
    if (state.logs.length > 400) state.logs.shift();

    const div = document.createElement('div');
    div.className = 'log-entry';
    div.innerHTML = `
      <span class="log-time">[${log.time}]</span>
      <span class="log-tag ${log.level}">${log.level}</span>
      ${log.wid ? `<span style="color: var(--accent-gold); font-size: 0.75rem;">[W#${log.wid}]</span>` : ''}
      <span class="log-msg">${escapeHtml(log.message)}</span>
    `;

    el.terminalLogs.appendChild(div);

    if (state.autoScrollLogs) {
      el.terminalLogs.scrollTop = el.terminalLogs.scrollHeight;
    }
  }

  // Harvested Links Vault
  async function fetchLinks() {
    try {
      const res = await fetch('/api/links');
      const data = await res.json();
      state.links = data.links || [];
      renderLinks(state.links);
    } catch (err) {
      console.error('Fetch links error', err);
    }
  }

  function renderLinks(links) {
    if (!el.linksTableBody) return;
    if (el.linksCountBadge) el.linksCountBadge.textContent = links.length.toString();

    if (links.length === 0) {
      el.linksTableBody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align: center; padding: 3rem; color: var(--text-dim);">
            Belum ada link ditemukan. Jalankan perburuan untuk memanen link redeem Google AI Pro.
          </td>
        </tr>
      `;
      return;
    }

    el.linksTableBody.innerHTML = links.map(item => `
      <tr class="vault-row">
        <td style="font-family: var(--font-mono); color: var(--text-dim);">#${item.id}</td>
        <td style="font-family: var(--font-mono); color: var(--accent-cyan); font-weight: 600;">
          ${formatPhone(item.phone)}
        </td>
        <td>
          <div class="link-url-cell" title="${item.link}">${item.link}</div>
        </td>
        <td style="font-size: 0.78rem; color: var(--text-dim);">
          ${item.created_at || '—'}
        </td>
        <td>
          <div style="display: flex; gap: 0.4rem;">
            <button class="btn btn-secondary btn-sm" onclick="window.copyToClipboard('${item.link}')" title="Copy Link">
              📋 Copy
            </button>
            <a href="${item.link}" target="_blank" class="btn btn-primary btn-sm" style="text-decoration: none;">
              Redeem ↗
            </a>
          </div>
        </td>
      </tr>
    `).join('');
  }

  // Recent History
  async function fetchHistory() {
    try {
      const res = await fetch('/api/hunts/recent?limit=40');
      const data = await res.json();
      renderHistory(data.hunts || []);
    } catch (err) {
      console.error('Fetch history error', err);
    }
  }

  function renderHistory(hunts) {
    const tbody = document.getElementById('history-table-body');
    if (!tbody) return;

    if (hunts.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-dim);">Belum ada riwayat attempt.</td></tr>`;
      return;
    }

    tbody.innerHTML = hunts.map(h => `
      <tr>
        <td style="font-family: var(--font-mono); color: var(--text-dim);">#${h.id}</td>
        <td style="font-family: var(--font-mono); color: var(--accent-cyan);">${formatPhone(h.phone)}</td>
        <td>
          ${h.logged_in ? '<span class="phase-badge phase-DONE">LOGIN OK</span>' : '<span class="phase-badge phase-ERROR">GAGAL</span>'}
        </td>
        <td>
          ${h.link ? `<a href="${h.link}" target="_blank" style="color: var(--accent-green); font-family: var(--font-mono); font-size: 0.8rem;">🎯 Link Found</a>` : '<span style="color: var(--text-dim);">Tidak ada promo</span>'}
        </td>
        <td style="font-size: 0.78rem; color: var(--text-dim);">${h.created_at}</td>
      </tr>
    `).join('');
  }

  // Fetch Config for Settings
  async function fetchConfig() {
    try {
      const res = await fetch('/api/config');
      const cfg = await res.json();
      state.config = cfg;

      document.getElementById('setting-provider').value = cfg.provider;
      const showGrizzly = (cfg.provider === 'grizzlysms' || cfg.provider === 'split' || cfg.provider === 'both');
      const showFiveSim = (cfg.provider === 'fivesim' || cfg.provider === 'split' || cfg.provider === 'both');
      document.getElementById('group-grizzly').style.display = showGrizzly ? 'block' : 'none';
      document.getElementById('group-fivesim').style.display = showFiveSim ? 'block' : 'none';

      document.getElementById('setting-grizzly-key').value = cfg.grizzly_api_key_masked || '';
      document.getElementById('setting-fivesim-key').value = cfg.fivesim_api_key_masked || '';
      document.getElementById('setting-max-price').value = cfg.max_price;
      document.getElementById('setting-concurrency').value = cfg.concurrency;
      document.getElementById('setting-cancel-delay').value = cfg.cancel_delay_seconds;
      document.getElementById('setting-otp-fail-delay').value = cfg.otp_fail_delay_seconds;
      document.getElementById('setting-tg-token').value = cfg.tg_bot_token_masked || '';
      document.getElementById('setting-tg-chat').value = cfg.tg_chat_id || '';
    } catch (err) {
      console.error('Fetch config error', err);
    }
  }

  // Global Helpers
  window.copyToClipboard = function(text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        showToast('📋 Link disalin ke clipboard!', 'success');
      });
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast('📋 Link disalin ke clipboard!', 'success');
    }
  };

  window.exportLinks = function(format) {
    window.location.href = `/api/links/export?format=${format}`;
  };

  function showToast(message, type = 'info') {
    if (!el.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    toast.innerHTML = `<span>${icons[type] || '🔔'}</span> <span>${message}</span>`;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  function formatPhone(p) {
    if (!p) return '';
    let clean = p.replace(/\D/g, '');
    if (clean.length === 12 && clean.startsWith('91')) {
      return `+91 ${clean.slice(2, 7)} ${clean.slice(7)}`;
    }
    return p;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function jsonStringify(obj) {
    return JSON.stringify(obj);
  }

})();
