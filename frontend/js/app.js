const App = {
  ws: null,
  isRecording: false,
  isUploading: false,
  isBooted: false,
  isAuthenticated: false,
  authUser: '',
  authRequired: false,
  authConfigured: true,
  appMode: 'desktop',
  capabilities: {
    live_capture: true,
    local_recording: true,
    file_upload: true,
  },
  meetingId: null,
  segments: [],
  summaryData: null,
  startTime: null,
  timerInterval: null,
  audioDebugInterval: null,
  devicePollInterval: null,
  connectionState: 'disconnected',
  searchQuery: '',
  transcriptionHealthLabel: 'Checking transcription',
  summaryHealthLabel: 'Checking summary',
  transcriptionReady: false,
  transcriptionDetail: '',
  isLocalRecording: false,
  localRecordingId: null,
  localRecordingFiles: [],
  localRecordingStartTime: null,
  localRecordingTimerInterval: null,
  localRecordingDownloadUrl: '',
  audioDebugData: null,
  connectedBluetoothDevices: [],
  bluetoothDevices: [],
  defaultSource: '',
  activeMode: 'idle',
  activeMeetingTitle: '',
  hasShownPrivacyToast: false,
  supportsPause: false,

  async init() {
    this.bindEvents();
    this.initializeInterface();
    await this.loadHealth();
    await this.restoreSession();
  },

  bindEvents() {
    document.getElementById('login-form')?.addEventListener('submit', (event) => this.handleGateSubmit(event));
    document.getElementById('btn-logout')?.addEventListener('click', () => this.lockStudio());

    document.getElementById('btn-start')?.addEventListener('click', () => this.startRecording());
    document.getElementById('btn-stop')?.addEventListener('click', () => this.stopRecording());
    document.getElementById('btn-start-inline')?.addEventListener('click', () => this.startRecording());
    document.getElementById('btn-stop-inline')?.addEventListener('click', () => this.stopRecording());
    document.getElementById('btn-pause')?.addEventListener('click', () => this.handlePauseRequest());

    document.getElementById('btn-copy-transcript')?.addEventListener('click', () => this.copyTranscript());
    document.getElementById('btn-clear-transcript')?.addEventListener('click', () => this.clearWorkspace());

    document.getElementById('btn-upload-audio')?.addEventListener('click', () => this.transcribeUploadedFile());
    document.getElementById('input-audio-file')?.addEventListener('change', (event) => this.onAudioFileSelected(event));
    document.getElementById('btn-start-local-recording')?.addEventListener('click', () => this.startLocalRecording());
    document.getElementById('btn-stop-local-recording')?.addEventListener('click', () => this.stopLocalRecording());
    document.getElementById('btn-download-local-recording')?.addEventListener('click', () => this.showToast('Downloading local recording', 'info'));

    document.getElementById('btn-refresh-audio')?.addEventListener('click', () => {
      this.loadDevices();
      this.loadAudioDebug();
    });
    document.getElementById('btn-refresh-history')?.addEventListener('click', () => this.loadHistory());

    document.getElementById('toggle-mic')?.addEventListener('change', () => {
      this.syncMicVisibility();
      this.updateMicSelectionUI();
    });
    document.getElementById('select-mic-device')?.addEventListener('change', () => this.updateMicSelectionUI());
    document.getElementById('transcript-search')?.addEventListener('input', (event) => this.onSearchInput(event));
    document.getElementById('btn-clear-search')?.addEventListener('click', () => this.clearSearch());

    document.querySelectorAll('[data-export]').forEach((button) => {
      button.addEventListener('click', () => this.handleExport(button));
    });

    document.addEventListener('keydown', (event) => this.handleKeyboardShortcuts(event));
  },

  initializeInterface() {
    this.syncMicVisibility();
    this.updateMicSelectionUI();
    this.setMeetingContext('', this.getIdleSubtitle());
    this.renderTranscriptPlaceholder(
      '◎',
      'Ready to transcribe',
      this.getIdleTranscriptDescription()
    );
    this.showSummaryPlaceholder(
      'Summary ready when the transcript is complete',
      this.getIdleSummaryDescription(),
      false
    );
    this.setUploadState('empty');
    this.setUploadHelperText('Full-file transcription often gives cleaner results than live capture for prerecorded audio.');
    this.setActivity('idle', 'Ready', 'The configured providers are idle and waiting for the next session.');
    this.updateLocalRecordingCard();
    this.renderLocalRecordingLibrary();
    this.updateStats();
    this.updateSearchMetrics();
    this.updateHeroSignals();
    this.updateUI();
  },

  async restoreSession() {
    try {
      const response = await this.apiFetch('/api/auth/me', { suppressUnauthorizedRedirect: true });
      const data = await response.json();
      this.applyServerContext(data);

      if (data.authenticated) {
        this.authenticate({ showWelcome: false, username: data.username || '' });
        return;
      }
    } catch (error) {
      console.warn('Could not restore session:', error);
    }

    this.showGate();
  },

  applyServerContext(data = {}) {
    this.appMode = data.app_mode || this.appMode || 'desktop';
    this.authRequired = data.auth_required ?? this.authRequired;
    this.authConfigured = data.auth_configured ?? this.authConfigured;
    this.capabilities = {
      ...this.capabilities,
      ...(data.capabilities || {}),
    };

    this.updateCapabilityUI();
  },

  showGate() {
    this.isAuthenticated = false;
    this.authUser = '';
    document.body.classList.remove('authenticated', 'app-welcome');
    const gate = document.getElementById('login-gate');
    const usernameInput = document.getElementById('access-username');
    const secretInput = document.getElementById('secret-word');
    const feedback = document.getElementById('gate-feedback');
    const submit = document.getElementById('btn-enter-gate');
    const submitText = document.getElementById('gate-btn-text');
    const toggle = document.getElementById('gate-visibility');
    const note = document.getElementById('gate-note');
    const copy = document.getElementById('gate-copy');

    gate?.classList.remove(
      'bg-gate--error',
      'bg-gate--success',
      'bg-gate--roaring',
      'bg-gate--welcome',
      'bg-gate--error-active'
    );
    if (feedback) {
      if (this.authRequired && !this.authConfigured) {
        feedback.textContent = 'Server auth is not configured yet.';
      } else {
        feedback.textContent = this.appMode === 'hosted'
          ? 'Sign in to access the hosted studio.'
          : 'Sign in to access the studio.';
      }
    }
    if (copy) {
      copy.textContent = this.appMode === 'hosted'
        ? 'This hosted studio supports uploaded-file transcription with backend-protected sessions.'
        : 'This studio uses server-side sessions. Sign in to open the workspace.';
    }
    if (note) {
      note.textContent = this.appMode === 'hosted'
        ? 'Hosted mode keeps upload-based transcription available and disables local machine audio capture.'
        : 'API routes and WebSocket access are protected by the backend session.';
    }
    if (usernameInput) {
      usernameInput.value = '';
      usernameInput.disabled = false;
    }
    if (secretInput) {
      secretInput.value = '';
      secretInput.type = 'password';
      secretInput.disabled = false;
      window.setTimeout(() => (usernameInput || secretInput).focus(), 120);
    }
    if (toggle) {
      toggle.setAttribute('aria-pressed', 'false');
      toggle.setAttribute('aria-label', 'Reveal password');
    }
    if (submit) {
      submit.disabled = !this.authConfigured;
    }
    if (submitText) submitText.textContent = 'Sign In';
  },

  async handleGateSubmit(event) {
    event.preventDefault();

    const gate = document.getElementById('login-gate');
    const usernameInput = document.getElementById('access-username');
    const secretInput = document.getElementById('secret-word');
    const feedback = document.getElementById('gate-feedback');
    const submit = document.getElementById('btn-enter-gate');
    const submitText = document.getElementById('gate-btn-text');
    const username = (usernameInput?.value || '').trim();
    const password = secretInput?.value || '';

    if (!username || !password) {
      gate?.classList.remove('bg-gate--success');
      gate?.classList.add('bg-gate--error');
      if (feedback) feedback.textContent = 'Username and password are both required.';
      this.showToast('Enter your username and password', 'error');
      window.setTimeout(() => gate?.classList.remove('bg-gate--error'), 820);
      (usernameInput || secretInput)?.focus();
      return;
    }

    if (submit) submit.disabled = true;
    if (submitText) submitText.textContent = 'Signing in...';

    try {
      const response = await this.apiFetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        suppressUnauthorizedRedirect: true,
      });
      const data = await response.json();

      gate?.classList.remove('bg-gate--error');
      gate?.classList.add('bg-gate--success');
      if (feedback) feedback.textContent = 'Welcome to Jamaluuu World';
      if (usernameInput) usernameInput.disabled = true;
      if (secretInput) secretInput.disabled = true;
      if (submitText) submitText.textContent = 'Entering...';
      this.applyServerContext(data);

      window.setTimeout(() => {
        gate?.classList.remove('bg-gate--success');
        this.authenticate({ showWelcome: true, username: data.username || username });
      }, 320);
    } catch (error) {
      gate?.classList.remove('bg-gate--success');
      gate?.classList.add('bg-gate--error');
      if (feedback) feedback.textContent = error.message || 'Sign-in failed.';
      if (submit) submit.disabled = false;
      if (submitText) submitText.textContent = 'Sign In';
      this.showToast(error.message || 'Sign-in failed', 'error');
      window.setTimeout(() => gate?.classList.remove('bg-gate--error'), 820);
      secretInput?.focus();
      secretInput?.select();
    }
  },

  authenticate({ showWelcome = false, username = '' } = {}) {
    this.isAuthenticated = true;
    this.authUser = username || this.authUser || '';
    document.body.classList.add('authenticated');

    if (showWelcome) {
      document.body.classList.add('app-welcome');
      window.setTimeout(() => document.body.classList.remove('app-welcome'), 2800);
    } else {
      document.body.classList.remove('app-welcome');
    }

    if (!this.isBooted) {
      this.bootApp();
    } else {
      this.resumeApp();
    }

    this.updateUI();
  },

  bootApp() {
    this.isBooted = true;
    this.loadHealth();
    this.loadHistory();
    if (this.capabilities.live_capture) {
      this.loadDevices();
      this.loadAudioDebug();
      this.connectWebSocket();
      this.startDevicePolling();
    }

    if (!this.hasShownPrivacyToast) {
      this.hasShownPrivacyToast = true;
      this.showToast('Transcription studio active', 'info');
    }
  },

  resumeApp() {
    if (this.capabilities.live_capture && (!this.ws || this.connectionState === 'disconnected')) {
      this.connectWebSocket();
    }
    this.loadHealth();
    this.loadHistory();
    if (this.capabilities.live_capture) {
      this.loadDevices();
      this.loadAudioDebug();
      this.startDevicePolling();
    }
  },

  async lockStudio(options = {}) {
    if (this.isRecording || this.isUploading || this.isLocalRecording) {
      this.showToast('Stop the active recording before locking the studio', 'error');
      return;
    }

    try {
      if (!options.skipServerLogout) {
        await fetch('/api/auth/logout', { method: 'POST' });
      }
    } catch (error) {
      console.warn('Could not end server session:', error);
    }

    this.completeLogout(options);
  },

  completeLogout(options = {}) {
    this.isAuthenticated = false;
    this.authUser = '';
    document.body.classList.remove('authenticated', 'app-welcome');

    if (this.ws) {
      this.ws.disconnect();
      this.ws = null;
    }

    this.connectionState = 'disconnected';
    this.stopDevicePolling();
    this.stopAudioDebugPolling();
    this.setConnectionLabel(this.capabilities.live_capture ? 'disconnected' : 'upload-only');
    this.connectionState = this.capabilities.live_capture ? 'disconnected' : 'upload-only';
    this.showGate();

    if (!options.silent) {
      this.showToast(options.reason || 'Signed out', 'info');
    }
  },

  async apiFetch(url, options = {}) {
    const { suppressUnauthorizedRedirect = false, ...fetchOptions } = options;
    const response = await fetch(url, fetchOptions);
    if (response.status === 401) {
      if (!suppressUnauthorizedRedirect) {
        this.handleUnauthorized();
      }
      throw new Error('Please sign in again.');
    }
    return response;
  },

  handleUnauthorized() {
    this.completeLogout({
      skipServerLogout: true,
      reason: 'Your session expired. Please sign in again.',
    });
  },

  setConnectionLabel(state) {
    const dot = document.getElementById('connection-dot');
    const text = document.getElementById('connection-text');

    if (dot) {
      dot.className = 'connection-dot';
      if (this.isRecording) {
        dot.classList.add('recording');
      } else if (state === 'connected') {
        dot.classList.add('connected');
      }
    }

    if (text) {
      text.textContent = state === 'connected'
        ? 'Connected'
        : state === 'upload-only'
          ? 'Upload only'
          : 'Disconnected';
    }
  },

  updateCapabilityUI() {
    const liveCard = document.getElementById('live-capture-card');
    const localCard = document.getElementById('local-recording-card');
    const diagnostics = document.getElementById('audio-diagnostics-card');
    const liveStatus = document.getElementById('live-capture-status');
    const headerSubtitle = document.querySelector('.app-subtitle');
    const brandSubtitle = document.querySelector('.gate__brand-sub');

    if (headerSubtitle) {
      headerSubtitle.textContent = this.appMode === 'hosted'
        ? 'Hosted transcription workspace'
        : 'Local AI Transcription Studio';
    }
    if (brandSubtitle) {
      brandSubtitle.textContent = this.appMode === 'hosted'
        ? 'Hosted AI Transcription Workspace'
        : 'Local AI Transcription Studio';
    }

    if (liveCard) {
      liveCard.classList.toggle('hidden', !this.capabilities.live_capture);
    }
    if (localCard) {
      localCard.classList.toggle('hidden', !this.capabilities.local_recording);
    }
    if (diagnostics) {
      diagnostics.classList.toggle('hidden', !this.capabilities.live_capture);
    }
    if (liveStatus) {
      liveStatus.textContent = this.capabilities.live_capture
        ? 'Live capture is available when the backend can access local system audio devices.'
        : 'Hosted mode disables server-side local audio capture. Use uploaded files instead.';
    }

    if (!this.capabilities.live_capture && !this.isRecording) {
      this.connectionState = 'upload-only';
      this.setConnectionLabel('upload-only');
    }

    this.setMeetingContext(
      this.activeMeetingTitle,
      this.capabilities.live_capture
        ? 'Capture live meetings or upload a recording to begin a transcription session.'
        : 'Upload an audio or meeting recording file to transcribe it in the hosted workspace.'
    );
  },

  connectWebSocket() {
    if (!this.capabilities.live_capture) {
      this.connectionState = 'upload-only';
      this.setConnectionLabel('upload-only');
      return;
    }

    if (this.ws) {
      this.ws.disconnect();
    }

    this.ws = new TranscriptionWebSocket(
      (segment) => this.onSegment(segment),
      (message) => this.onStatus(message),
      (data) => this.onSummary(data),
      (message) => this.showToast(message, 'error'),
      (state) => this.onConnectionChange(state),
      (data) => this.onSessionStarted(data)
    );
    this.ws.connect();
  },

  async loadHealth() {
    try {
      const response = await fetch('/health');
      const data = await response.json();
      this.applyServerContext(data);
      this.updateTranscriptionStatus(data);
      this.updateSummaryStatus(data);
    } catch (error) {
      this.updateTranscriptionStatus({
        transcription_engine: 'openai',
        transcription_provider: 'Transcription provider',
        transcription_ready: false,
        transcription_model_available: false,
        transcription_detail: 'Cloud transcription is disabled until the provider is configured.',
      });
      this.updateSummaryStatus({
        summary_engine: 'openai',
        summary_provider: 'Summary provider',
        summary_ready: false,
        summary_model_available: false,
        summary_detail: 'Fallback summary mode active. The summary provider could not be reached.',
      });
    }
  },

  updateTranscriptionStatus(data) {
    const badge = document.getElementById('badge-transcription-provider');

    const provider = data.transcription_provider
      || (data.transcription_engine === 'faster-whisper' ? 'faster-whisper' : 'OpenAI');
    const ready = Boolean(data.transcription_ready);
    const modelAvailable = data.transcription_model_available !== false;

    let label = 'Transcription offline';
    let statusClass = 'warning';

    if (!this.capabilities.file_upload) {
      label = 'Transcription unavailable';
      statusClass = 'warning';
    } else if (ready && modelAvailable) {
      label = provider;
      statusClass = 'success';
    }

    this.transcriptionHealthLabel = label;
    this.transcriptionReady = ready && modelAvailable;
    this.transcriptionDetail = data.transcription_detail || '';

    if (badge) {
      badge.textContent = label;
      badge.classList.remove('ready', 'warning');
      badge.classList.add(statusClass === 'success' ? 'ready' : 'warning');
    }
  },

  updateSummaryStatus(data) {
    const summaryStatus = document.getElementById('summary-status');
    const badge = document.getElementById('badge-summary-provider');
    const headerSummary = document.getElementById('header-summary-text');

    const provider = data.summary_provider || (data.summary_engine === 'ollama' ? 'Ollama' : 'OpenAI');
    const ready = Boolean(data.summary_ready);
    const modelAvailable = data.summary_model_available !== false;

    let label = 'Fallback summary';
    let statusClass = 'warning';
    let detail = data.summary_detail || 'Fallback summary mode active.';

    if (ready && modelAvailable) {
      label = `${provider} ready`;
      statusClass = 'success';
    }

    this.summaryHealthLabel = label;

    if (summaryStatus) {
      summaryStatus.className = `service-pill ${statusClass}`;
      summaryStatus.textContent = detail;
    }

    if (badge) {
      badge.textContent = label;
      badge.classList.remove('ready', 'warning');
      badge.classList.add(statusClass === 'success' ? 'ready' : 'warning');
    }

    if (headerSummary) {
      headerSummary.textContent = label;
    }

    this.updateHeroSignals();
  },

  async loadDevices() {
    if (!this.capabilities.live_capture) {
      this.connectedBluetoothDevices = [];
      this.bluetoothDevices = [];
      this.defaultSource = '';
      this.updateMicSelectionUI([]);
      return;
    }
    try {
      const response = await this.apiFetch('/api/transcription/devices');
      const data = await response.json();
      this.connectedBluetoothDevices = Array.isArray(data.connected_bluetooth_devices)
        ? data.connected_bluetooth_devices
        : [];
      this.bluetoothDevices = Array.isArray(data.bluetooth_devices)
        ? data.bluetooth_devices
        : [];
      this.defaultSource = data.default_source || '';
      this.populateDeviceSelect('select-system-device', this.filterSystemDevices(data.devices.filter((device) => device.is_monitor)), data.default_monitor);
      this.populateDeviceSelect('select-mic-device', data.devices.filter((device) => !device.is_monitor), data.default_mic);
      this.updateMicSelectionUI(data.devices.filter((device) => !device.is_monitor), data.default_mic);
    } catch (error) {
      console.warn('Could not load devices:', error);
      this.connectedBluetoothDevices = [];
      this.bluetoothDevices = [];
      this.defaultSource = '';
      this.updateMicSelectionUI([]);
    }
  },

  filterSystemDevices(devices) {
    const seen = new Set();
    return devices.filter((device) => {
      const name = String(device?.name || '').toLowerCase();
      if (name === 'default' || name === 'pulse') return false;
      if (seen.has(name)) return false;
      seen.add(name);
      return true;
    });
  },

  populateDeviceSelect(selectId, devices, defaultDevice) {
    const select = document.getElementById(selectId);
    if (!select) return;
    const previousValue = select.value;

    if (selectId === 'select-mic-device') {
      select.innerHTML = '<option value="">Auto-detect microphone</option>';
    } else {
      select.innerHTML = '<option value="">Auto-detect</option>';
    }

    devices.forEach((device) => {
      const option = document.createElement('option');
      option.value = device.index;
      option.textContent = this.formatDeviceOption(device);
      if (previousValue && String(device.index) === String(previousValue)) {
        option.selected = true;
      }
      select.appendChild(option);
    });

    if (!previousValue && defaultDevice && selectId !== 'select-mic-device') {
      select.value = String(defaultDevice.index);
    }
  },

  formatDeviceOption(device) {
    if (!device) return '';
    const prefix = device.connection_label ? `${device.connection_label} · ` : '';
    const name = String(device.name || '').replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s+/g, ' ').trim();
    return `${prefix}${name}`;
  },

  updateMicSelectionUI(devices = null, defaultDevice = null) {
    const toggle = document.getElementById('toggle-mic');
    const select = document.getElementById('select-mic-device');
    const pill = document.getElementById('mic-selection-pill');
    const note = document.getElementById('mic-device-note');
    const summary = document.getElementById('mic-device-summary');

    if (!toggle || !select || !pill || !note || !summary) return;

    const knownDevices = devices || Array.from(select.options)
      .filter((option) => option.value && option.value !== 'none')
      .map((option) => {
        const label = option.textContent || '';
        const [connectionLabel, ...rest] = label.split(' · ');
        return {
          name: rest.length ? rest.join(' · ') : label,
          connection_label: rest.length ? connectionLabel : '',
        };
      });

    const selectedOption = select.options[select.selectedIndex];
    const selectedLabel = selectedOption?.textContent || '';
    const bluetoothDevices = knownDevices.filter((device) => (device.connection_label || '').toLowerCase().includes('bluetooth'));
    const wiredDevices = knownDevices.filter((device) => (device.connection_label || '').toLowerCase().includes('wired'));
    const builtInDevices = knownDevices.filter((device) => (device.connection_label || '').toLowerCase().includes('built in'));
    const bluetoothState = this.getBluetoothState(bluetoothDevices, defaultDevice);

    pill.className = 'soft-pill';

    if (!knownDevices.length) {
      pill.textContent = 'No mic detected';
      pill.classList.add('error');
      note.textContent = 'No microphone input is available to the app right now.';
      summary.innerHTML = '<strong>No microphone inputs detected</strong><div class="summary-line">Check your system sound input settings, then click Refresh.</div>';
      return;
    }

    if (!toggle.checked) {
      pill.textContent = 'Mic off';
      note.textContent = this.buildMicAvailabilityNote(bluetoothState, wiredDevices, builtInDevices);
      summary.innerHTML = this.buildMicSummaryMarkup(knownDevices, bluetoothState, defaultDevice);
      return;
    }

    if (!select.value && defaultDevice) {
      pill.textContent = `Auto: ${this.formatDeviceOption(defaultDevice)}`;
    } else if (!select.value) {
      pill.textContent = 'Auto-detect microphone';
    } else {
      pill.textContent = selectedLabel;
    }

    pill.classList.add('active');
    note.textContent = this.buildMicAvailabilityNote(bluetoothState, wiredDevices, builtInDevices);
    summary.innerHTML = this.buildMicSummaryMarkup(knownDevices, bluetoothState, defaultDevice);
  },

  getBluetoothState(bluetoothInputDevices = [], defaultDevice = null) {
    const paired = Array.isArray(this.bluetoothDevices) ? this.bluetoothDevices : [];
    const connected = paired.filter((device) => device.connected);
    const disconnected = paired.filter((device) => !device.connected);
    const activeBluetoothDevice = (
      defaultDevice
      && String(defaultDevice.connection || '').toLowerCase() === 'bluetooth'
      && defaultDevice.name
    ) ? defaultDevice.name : (
      this.defaultSource.startsWith('bluez_input.')
        ? (connected[0]?.name || this.connectedBluetoothDevices[0] || '')
        : ''
    );

    return {
      paired,
      connected,
      disconnected,
      availableInputs: bluetoothInputDevices,
      activeName: activeBluetoothDevice,
    };
  },

  buildMicAvailabilityNote(bluetoothState, wiredDevices, builtInDevices) {
    if (bluetoothState.activeName) {
      return `Bluetooth connected and active: ${bluetoothState.activeName}.`;
    }
    if (bluetoothState.connected.length && bluetoothState.availableInputs.length) {
      return `Bluetooth connected: ${bluetoothState.connected.map((device) => device.name).join(', ')}. Its microphone input is available.`;
    }
    if (bluetoothState.connected.length) {
      return `Bluetooth connected: ${bluetoothState.connected.map((device) => device.name).join(', ')}. Linux has not exposed its microphone input yet.`;
    }
    if (wiredDevices.length && builtInDevices.length) {
      return 'The app currently sees wired and built-in microphone sources.';
    }
    if (wiredDevices.length) {
      return 'The app currently sees wired microphone sources.';
    }
    if (builtInDevices.length) {
      return 'The app currently sees built-in microphone sources.';
    }
    return 'Detected microphone sources can be selected here when the system exposes them.';
  },

  buildMicSummaryMarkup(devices, bluetoothState, defaultDevice = null) {
    const bluetoothInputLabels = bluetoothState.availableInputs.map((device) => this.formatDeviceOption(device));
    const otherInputs = devices
      .filter((device) => String(device.connection || '').toLowerCase() !== 'bluetooth')
      .map((device) => this.formatDeviceOption(device));
    const lines = [];

    if (bluetoothState.activeName) {
      lines.push(`<div class="summary-line">Bluetooth mic active: ${this.escapeHtml(bluetoothState.activeName)}</div>`);
    } else if (defaultDevice && String(defaultDevice.connection || '').toLowerCase() === 'bluetooth') {
      lines.push(`<div class="summary-line">Bluetooth mic active: ${this.escapeHtml(defaultDevice.name)}</div>`);
    }

    if (bluetoothState.connected.length) {
      lines.push(`<div class="summary-line">Bluetooth connected: ${this.escapeHtml(bluetoothState.connected.map((device) => device.name).join(', '))}</div>`);
    }

    if (bluetoothInputLabels.length) {
      lines.push(`<div class="summary-line">Bluetooth mic available: ${this.escapeHtml(bluetoothInputLabels.join(', '))}</div>`);
    }

    if (bluetoothState.disconnected.length) {
      lines.push(`<div class="summary-line">Paired, not connected: ${this.escapeHtml(bluetoothState.disconnected.map((device) => device.name).join(', '))}</div>`);
    }

    if (otherInputs.length) {
      lines.push(`<div class="summary-line">Other mic inputs: ${this.escapeHtml(otherInputs.join(', '))}</div>`);
    }

    return `<strong>Microphone status</strong>${lines.join('')}`;
  },

  async loadAudioDebug() {
    if (!this.capabilities.live_capture) {
      this.renderAudioDebug({
        recording: false,
        capture_target: null,
        default_sink: null,
        meeting_streams: [],
        active_capture: [],
        hosted_message: 'Hosted mode does not expose local audio routing.',
      });
      return;
    }
    try {
      const response = await this.apiFetch('/api/transcription/audio-debug');
      const data = await response.json();
      this.renderAudioDebug(data);
    } catch (error) {
      this.renderAudioDebug({
        recording: false,
        capture_target: null,
        default_sink: null,
        meeting_streams: [],
        active_capture: [],
      });
    }
  },

  renderAudioDebug(data) {
    this.audioDebugData = data;

    const pill = document.getElementById('audio-debug-pill');
    const captureTarget = document.getElementById('audio-route-target');
    const system = document.getElementById('audio-route-system');
    const mic = document.getElementById('audio-route-mic');
    const sink = document.getElementById('audio-route-sink');
    const streams = document.getElementById('audio-route-streams');
    const note = document.getElementById('audio-route-note');

    if (!pill || !captureTarget || !system || !mic || !sink || !streams || !note) return;

    pill.className = 'audio-debug-pill';

    const activeCapture = Array.isArray(data.active_capture) ? data.active_capture : [];
    const systemCapture = activeCapture.find((item) => item.source_type === 'system');
    const micCapture = activeCapture.find((item) => item.source_type === 'microphone');
    const meetingStreams = (data.meeting_streams || []).join(', ') || 'None detected';
    const qualityWarning = data.quality_warning || '';

    if (!this.capabilities.live_capture && data.hosted_message) {
      pill.classList.add('warning');
      pill.textContent = 'Upload-only hosted mode';
    } else if (data.recording) {
      pill.classList.add('live');
      pill.textContent = `Live capture active${data.meeting_title ? `: ${data.meeting_title}` : ''}`;
    } else {
      pill.classList.add('warning');
      pill.textContent = 'Recorder idle. Route info shown from current system state.';
    }

    captureTarget.textContent = data.capture_target === 'meeting_stream'
      ? 'Direct meeting stream'
      : (data.capture_target === 'sink_monitor' ? 'Active sink monitor' : 'Unknown');
    system.textContent = systemCapture
      ? `${systemCapture.device_name} · ${systemCapture.input_rate}Hz / ${systemCapture.input_channels}ch`
      : this.describeDevice(data.selected_system_device) || 'Not armed';
    mic.textContent = micCapture
      ? `${micCapture.device_name} · ${micCapture.input_rate}Hz / ${micCapture.input_channels}ch`
      : this.describeDevice(data.selected_mic_device) || 'Mic not included';
    sink.textContent = data.default_sink || 'Unknown';
    streams.textContent = meetingStreams;

    if (!this.capabilities.live_capture && data.hosted_message) {
      note.textContent = data.hosted_message;
    } else if (qualityWarning) {
      note.textContent = qualityWarning;
    } else if (data.capture_target === 'meeting_stream') {
      note.textContent = 'Best case: the app can see a direct meeting stream like Zoom.';
    } else if (meetingStreams !== 'None detected') {
      note.textContent = 'A meeting app exists, but capture is falling back to the active sink monitor.';
    } else {
      note.textContent = 'No meeting stream is visible right now. The app will capture whatever is playing through the active sink.';
    }

    this.updateHeroSignals();
  },

  describeDevice(device) {
    if (!device) return '';
    return `${device.name} · ${device.sample_rate}Hz / ${device.channels}ch`;
  },

  startAudioDebugPolling() {
    this.stopAudioDebugPolling();
    this.loadAudioDebug();
    this.audioDebugInterval = window.setInterval(() => {
      this.loadAudioDebug();
    }, 3000);
  },

  stopAudioDebugPolling() {
    if (this.audioDebugInterval) {
      window.clearInterval(this.audioDebugInterval);
      this.audioDebugInterval = null;
    }
  },

  startDevicePolling() {
    if (!this.capabilities.live_capture) return;
    this.stopDevicePolling();
    this.devicePollInterval = window.setInterval(() => {
      if (this.isRecording || this.isUploading || !this.isAuthenticated) return;
      this.loadDevices();
      this.loadAudioDebug();
    }, 12000);
  },

  stopDevicePolling() {
    if (this.devicePollInterval) {
      window.clearInterval(this.devicePollInterval);
      this.devicePollInterval = null;
    }
  },

  async loadHistory() {
    try {
      const requests = [
        this.apiFetch('/api/meetings/')
          .then(async (response) => {
            if (!response.ok) throw new Error('Could not load meetings');
            return response.json();
          })
          .catch((error) => {
            console.warn('Could not load meetings:', error);
            return { meetings: [] };
          }),
      ];

      if (this.capabilities.local_recording) {
        requests.push(
          this.apiFetch('/api/transcription/local-recording/files')
            .then(async (response) => {
              if (!response.ok) throw new Error('Could not load local recordings');
              return response.json();
            })
            .catch((error) => {
              console.warn('Could not load local recordings:', error);
              return { recordings: [] };
            })
        );
      } else {
        requests.push(Promise.resolve({ recordings: [] }));
      }

      const [meetingsData, recordingsData] = await Promise.all(requests);

      this.localRecordingFiles = Array.isArray(recordingsData.recordings) ? recordingsData.recordings : [];
      this.renderLocalRecordingLibrary(this.localRecordingFiles);
      this.renderHistory({
        meetings: meetingsData.meetings || [],
        recordings: this.localRecordingFiles,
      });
    } catch (error) {
      console.warn('Could not load history:', error);
    }
  },

  renderHistory({ meetings = [], recordings = [] } = {}) {
    const list = document.getElementById('meeting-list');
    if (!list) return;

    if (!meetings.length && !recordings.length) {
      list.innerHTML = `
        <div class="transcript-empty compact-empty">
          <div class="transcript-empty-icon">◌</div>
          <h3>No history yet</h3>
          <p>Completed transcriptions will appear here.</p>
        </div>
      `;
      return;
    }

    const sections = [];

    if (recordings.length) {
      sections.push(this.renderHistorySection(
        'Local Recordings',
        'Saved WAV files from the backend recorder.',
        recordings.slice(0, 12).map((recording) => this.renderLocalRecordingHistoryItem(recording)).join('')
      ));
    }

    if (meetings.length) {
      sections.push(this.renderHistorySection(
        'Meetings',
        'Completed live sessions and uploaded transcripts.',
        meetings.slice(0, 12).map((meeting) => this.renderMeetingHistoryItem(meeting)).join('')
      ));
    }

    list.innerHTML = sections.join('');

    list.querySelectorAll('[data-history-view]').forEach((button) => {
      button.addEventListener('click', () => this.viewMeeting(button.dataset.historyView));
    });

    list.querySelectorAll('[data-history-delete]').forEach((button) => {
      button.addEventListener('click', () => this.deleteMeeting(button.dataset.historyDelete));
    });
  },

  renderHistorySection(title, description, itemsMarkup) {
    return `
      <section class="history-section">
        <div class="history-section-header">
          <h3>${this.escapeHtml(title)}</h3>
          <p>${this.escapeHtml(description)}</p>
        </div>
        ${itemsMarkup}
      </section>
    `;
  },

  renderMeetingHistoryItem(meeting) {
    const isActive = this.meetingId === meeting.id ? 'active' : '';
    return `
      <div class="meeting-item ${isActive}" data-id="${meeting.id}">
        <div class="meeting-item-info">
          <h4>${this.escapeHtml(meeting.title || 'Untitled Meeting')}</h4>
          <p>${this.escapeHtml(this.formatDateTime(meeting.created_at))} · ${meeting.word_count || 0} words</p>
        </div>
        <div class="meeting-item-actions">
          <button class="btn btn-ghost btn-inline" data-history-view="${meeting.id}" type="button">View</button>
          <button class="btn btn-ghost btn-inline" data-history-delete="${meeting.id}" type="button">Delete</button>
        </div>
      </div>
    `;
  },

  renderLocalRecordingHistoryItem(recording) {
    const duration = Number(recording.duration_seconds) > 0
      ? this.formatTime(recording.duration_seconds)
      : '00:00';
    const meta = [
      this.formatDateTime(recording.created_at),
      this.formatBytes(recording.file_size_bytes || 0),
      duration,
    ];

    return `
      <div class="meeting-item">
        <div class="meeting-item-info">
          <h4>${this.escapeHtml(recording.file_name || 'Local recording.wav')}</h4>
          <p>${this.escapeHtml(meta.join(' · '))}</p>
        </div>
        <div class="meeting-item-actions">
          <a
            class="btn btn-ghost btn-inline"
            href="${this.escapeHtml(recording.download_url || '#')}"
            download="${this.escapeHtml(recording.download_name || recording.file_name || 'local-recording.wav')}"
          >Download</a>
        </div>
      </div>
    `;
  },

  renderLocalRecordingLibrary(recordings = this.localRecordingFiles) {
    const list = document.getElementById('local-recording-list');
    const count = document.getElementById('local-recording-count');
    if (!list || !count) return;

    const safeRecordings = Array.isArray(recordings) ? recordings : [];
    count.textContent = `${safeRecordings.length} ${safeRecordings.length === 1 ? 'file' : 'files'}`;

    if (!safeRecordings.length) {
      list.innerHTML = '<div class="local-recording-list-empty">No saved recordings yet.</div>';
      return;
    }

    list.innerHTML = safeRecordings.map((recording) => this.renderLocalRecordingLibraryItem(recording)).join('');
  },

  renderLocalRecordingLibraryItem(recording) {
    const duration = Number(recording.duration_seconds) > 0
      ? this.formatTime(recording.duration_seconds)
      : '00:00';

    return `
      <article class="local-recording-item">
        <div class="local-recording-item-main">
          <div class="local-recording-item-top">
            <span class="soft-pill">${duration}</span>
            <span class="file-size">${this.formatBytes(recording.file_size_bytes || 0)}</span>
          </div>
          <strong class="local-recording-item-title">${this.escapeHtml(recording.file_name || 'Local recording.wav')}</strong>
          <p class="local-recording-item-meta">${this.escapeHtml(this.formatDateTime(recording.created_at))}</p>
        </div>
        <div class="local-recording-item-actions">
          <a
            class="btn btn-ghost btn-inline"
            href="${this.escapeHtml(recording.download_url || '#')}"
            download="${this.escapeHtml(recording.download_name || recording.file_name || 'local-recording.wav')}"
          >Download</a>
        </div>
      </article>
    `;
  },

  startRecording() {
    if (!this.capabilities.live_capture) {
      this.showToast('Hosted mode supports uploaded-file transcription only.', 'info');
      return;
    }
    if (this.isRecording || this.isUploading || this.isLocalRecording) return;

    const title = this.ensureMeetingTitle('Meeting');
    const micToggle = document.getElementById('toggle-mic');
    const micSelect = document.getElementById('select-mic-device');
    const micAudio = Boolean(micToggle?.checked);
    const systemDeviceIndex = document.getElementById('select-system-device')?.value || null;
    const micDeviceIndex = micAudio ? (micSelect?.value || null) : null;

    const sent = this.ws?.startTranscription({
      title,
      systemAudio: true,
      micAudio,
      systemDeviceIndex: systemDeviceIndex ? parseInt(systemDeviceIndex, 10) : null,
      micDeviceIndex: micDeviceIndex ? parseInt(micDeviceIndex, 10) : null,
    });

    if (!sent) {
      this.showToast('Not connected to server. Retrying...', 'error');
      this.connectWebSocket();
      return;
    }

    this.isRecording = true;
    this.meetingId = null;
    this.segments = [];
    this.summaryData = null;
    this.startTime = Date.now();
    this.activeMode = 'live';

    this.setMeetingContext(title, 'Listening for live speech from your configured capture sources.');
    this.renderTranscriptPlaceholder(
      '◉',
      'Listening for speech...',
      'Transcript segments will appear here in real time as the configured speech-to-text provider processes the live audio stream.'
    );
    this.showSummaryPlaceholder(
      'Summary will be ready after you stop the session',
      'The configured summary provider or the fallback summarizer will organize key points, decisions, action items, and follow-ups.',
      false
    );
    this.setActivity('live', 'Live capture active', 'The configured speech-to-text provider is processing incoming audio.');

    this.updateStats();
    this.updateUI();
    this.updateHeroSignals();
    this.startTimer();
    this.startAudioDebugPolling();
    this.onStatus('Transcription started. Listening...', 'success');
    this.showToast('Live transcription started', 'success');
  },

  stopRecording() {
    if (!this.isRecording || this.isUploading) return;

    this.ws?.stopTranscription();
    this.isRecording = false;
    this.stopTimer();
    this.updateUI();
    this.setActivity('summarizing', 'Generating summary', 'The configured summary provider is organizing the final transcript.');
    this.showSummaryPlaceholder(
      'Preparing summary',
      'The configured summary provider or the fallback summarizer is organizing the transcript now.',
      true
    );
    this.onStatus('Stopping transcription and generating summary...', 'info');
    this.stopAudioDebugPolling();
    this.loadAudioDebug();
    this.updateHeroSignals();
  },

  async startLocalRecording() {
    if (!this.capabilities.local_recording) {
      this.showToast('Local recording is only available in desktop mode.', 'info');
      return;
    }
    if (this.isRecording || this.isUploading || this.isLocalRecording) return;

    const title = this.ensureMeetingTitle('Local Recording');
    const systemDeviceIndex = document.getElementById('select-system-device')?.value || null;

    try {
      const response = await this.apiFetch('/api/transcription/local-recording/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          system_device_index: systemDeviceIndex ? parseInt(systemDeviceIndex, 10) : null,
        }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || 'Could not start local recording');
      }

      this.isLocalRecording = true;
      this.localRecordingId = data.recording_id || null;
      this.localRecordingStartTime = Date.now();
      this.localRecordingDownloadUrl = '';
      this.setText('local-recording-status', data.message || 'Local recording started.');
      this.setText('local-recording-file-pill', 'Recording...');
      this.setText('local-recording-file-name', data.file_name || 'Recording in progress');
      this.setText(
        'local-recording-file-meta',
        data.quality_warning
          || `${data.device_name || 'System audio'} is being saved locally in the backend.`
      );
      this.setText('local-recording-file-size', 'REC');
      this.updateLocalRecordingCard();
      this.startLocalRecordingTimer();
      this.updateUI();
      this.updateHeroSignals();
      this.showToast('Local recording started', 'success');
    } catch (error) {
      this.showToast(error.message || 'Could not start local recording', 'error');
    }
  },

  async stopLocalRecording() {
    if (!this.isLocalRecording) return;

    try {
      const response = await this.apiFetch('/api/transcription/local-recording/stop', {
        method: 'POST',
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || 'Could not stop local recording');
      }

      this.isLocalRecording = false;
      this.localRecordingDownloadUrl = data.download_url || '';
      this.localRecordingId = data.recording_id || null;
      this.localRecordingStartTime = null;
      this.stopLocalRecordingTimer();

      this.setText('local-recording-status', data.message || 'Local recording saved.');
      this.setText('local-recording-file-pill', 'Ready to download');
      this.setText('local-recording-file-name', data.file_name || 'Local recording saved');
      this.setText(
        'local-recording-file-meta',
        `${data.device_name || 'System audio'} recorded locally. Duration ${this.formatTime(data.duration_seconds || 0)}.`
      );
      this.setText('local-recording-file-size', this.formatBytes(data.file_size_bytes || 0));
      this.updateLocalRecordingCard({
        durationSeconds: data.duration_seconds || 0,
        downloadUrl: data.download_url || '',
      });
      await this.loadHistory();
      this.updateUI();
      this.updateHeroSignals();
      this.showToast('Local recording saved', 'success');
    } catch (error) {
      this.showToast(error.message || 'Could not stop local recording', 'error');
    }
  },

  onSessionStarted(data) {
    this.meetingId = data?.meeting_id || null;
    if (data?.title) {
      const titleInput = document.getElementById('input-title');
      if (titleInput) titleInput.value = data.title;
      this.setMeetingContext(data.title, 'Live capture in progress.');
    }
    this.updateUI();
  },

  onSegment(segment) {
    this.segments.push(segment);
    this.appendSegment(segment);
    this.updateStats();
    this.updateSearchMetrics();
  },

  onStatus(message, tone) {
    const statusText = document.querySelector('#status-bar .status-text');
    const statusIcon = document.getElementById('status-icon');
    const resolvedTone = tone || this.resolveToneFromMessage(message);

    if (statusText) statusText.textContent = message;
    if (statusIcon) statusIcon.textContent = resolvedTone === 'success' ? '✓' : resolvedTone === 'error' ? '!' : 'i';

    if (message.includes('Generating summary')) {
      this.setActivity('summarizing', 'Generating summary', 'The transcript is complete. The configured summary provider is running now.');
      this.showSummaryPlaceholder(
        'Preparing summary',
        'The summary card will populate as soon as the configured summary provider finishes.',
        true
      );
    }

    this.updateHeroSignals();
  },

  onSummary(data) {
    this.summaryData = data;
    this.renderSummary(data);
    this.loadHistory();
    this.loadHealth();
    this.loadAudioDebug();
    this.setActivity('review', 'Summary ready', 'Key points, decisions, and actions have been assembled for review.');
    this.onStatus('Meeting transcription complete. Summary ready.', 'success');
    this.showToast('Meeting summary ready', 'success');
    this.updateHeroSignals();
  },

  onConnectionChange(state) {
    this.connectionState = state;
    this.setConnectionLabel(state);
    this.updateUI();
    this.updateHeroSignals();
  },

  onAudioFileSelected(event) {
    const file = event?.target?.files?.[0] || null;
    const uploadTitle = document.getElementById('input-upload-title');

    if (file && uploadTitle && !uploadTitle.value.trim()) {
      const cleanedName = file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
      uploadTitle.value = cleanedName || this.generateMeetingTitle('Uploaded Audio');
    }

    if (file) {
      this.setUploadState('selected', {
        name: file.name,
        size: file.size,
        note: 'Ready for full-file transcription through the configured backend provider pipeline.',
      });
    } else {
      this.setUploadState('empty');
    }
  },

  async transcribeUploadedFile() {
    if (this.isRecording || this.isUploading) return;

    const fileInput = document.getElementById('input-audio-file');
    const file = fileInput?.files?.[0];

    if (!file) {
      this.showToast('Choose an audio file first', 'error');
      return;
    }

    const uploadTitleInput = document.getElementById('input-upload-title');
    const uploadTitle = uploadTitleInput?.value.trim()
      || file.name.replace(/\.[^.]+$/, '')
      || this.generateMeetingTitle('Uploaded Audio');

    if (uploadTitleInput && !uploadTitleInput.value.trim()) {
      uploadTitleInput.value = uploadTitle;
    }

    const meetingTitleInput = document.getElementById('input-title');
    if (meetingTitleInput && !meetingTitleInput.value.trim()) {
      meetingTitleInput.value = uploadTitle;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', uploadTitle);

    this.isUploading = true;
    this.meetingId = null;
    this.segments = [];
    this.summaryData = null;
    this.activeMode = 'upload';

    this.stopAudioDebugPolling();
    this.setMeetingContext(uploadTitle, 'Processing the uploaded audio file through the configured transcription pipeline.');
    this.renderTranscriptPlaceholder(
      '▣',
      'Processing uploaded audio...',
      'The backend is transcribing the full file. This view will refresh when the result is ready.'
    );
    this.showSummaryPlaceholder(
      'Generating transcript and summary',
      'The uploaded file is being processed now. Summary sections will populate automatically when finished.',
      true
    );
    this.setActivity('upload', 'Processing uploaded audio', 'Full-file transcription is running through the configured provider.');
    this.setUploadState('working', {
      name: file.name,
      size: file.size,
      note: 'Processing the uploaded audio file. Keep this tab open while the transcription provider works.',
    });
    this.setUploadHelperText(`Transcribing ${file.name}. Keep this tab open while the provider processes the file.`, 'working');
    this.updateStats();
    this.updateUI();
    this.onStatus('Processing uploaded audio file...', 'info');

    try {
      const response = await this.apiFetch('/api/transcription/file', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const message = await this.readErrorMessage(response);
        throw new Error(message || 'Upload transcription failed');
      }

      const data = await response.json();
      this.loadTranscriptionResult(data);
      this.setUploadState('success', {
        name: file.name,
        size: file.size,
        note: 'Upload complete. The transcript and summary are ready for review.',
      });
      this.setUploadHelperText('Finished. You can upload another file anytime.', 'success');
      this.showToast('Audio file transcribed successfully', 'success');
      this.loadHistory();
      this.loadHealth();
      if (this.capabilities.live_capture) {
        this.loadAudioDebug();
      }
    } catch (error) {
      this.meetingId = null;
      this.segments = [];
      this.summaryData = null;
      this.activeMode = 'idle';
      this.renderTranscriptPlaceholder(
        '!',
        'Upload transcription failed',
        error.message || 'Something went wrong while processing the audio file.'
      );
      this.showSummaryPlaceholder(
        'Summary unavailable',
        'Processing failed before a summary could be prepared.',
        false
      );
      this.setActivity('idle', 'Idle', 'The configured providers are ready for the next job.');
      this.setUploadState('error', {
        name: file.name,
        size: file.size,
        note: error.message || 'Upload transcription failed.',
      });
      this.setUploadHelperText(error.message || 'Upload transcription failed.', 'error');
      this.updateStats();
      this.onStatus('Upload transcription failed.', 'error');
      this.showToast(error.message || 'Failed to transcribe audio file', 'error');
    } finally {
      this.isUploading = false;
      this.updateUI();
      this.updateHeroSignals();
    }
  },

  loadTranscriptionResult(data) {
    this.meetingId = data.meeting_id || null;
    this.segments = Array.isArray(data.segments) ? data.segments : [];
    this.summaryData = data.summary || null;
    this.isRecording = false;
    this.isUploading = false;
    this.activeMode = 'review';

    this.stopTimer();
    this.startTime = null;

    this.setMeetingContext(data.title || 'Uploaded Audio', 'Uploaded audio processed. Review, search, export, or load another meeting.');
    this.renderTranscriptSegments(this.segments);
    this.updateStats();

    if (this.summaryData) {
      this.renderSummary({
        summary: this.summaryData,
        stats: data.stats || {},
      });
    } else {
      this.showSummaryPlaceholder(
        'Summary unavailable',
        'This transcription completed without a summary response from the backend.',
        false
      );
    }

    this.setActivity('review', 'Transcript ready', 'Review, search, copy, or export the completed transcript.');
    this.onStatus(`Audio file processed: ${data.title || 'Uploaded Audio'}`, 'success');
    this.updateUI();
    this.updateHeroSignals();
  },

  appendSegment(segment) {
    const area = document.getElementById('transcript-area');
    if (!area) return;

    const shouldStick = area.scrollHeight - area.scrollTop - area.clientHeight < 90 || this.isRecording;
    const empty = area.querySelector('.transcript-empty');
    if (empty) empty.remove();

    const wrapper = document.createElement('div');
    wrapper.innerHTML = this.renderSegmentMarkup(segment);
    const node = wrapper.firstElementChild;
    if (node) {
      area.appendChild(node);
    }

    if (shouldStick) {
      area.scrollTop = area.scrollHeight;
    }
  },

  renderTranscriptSegments(segments) {
    const area = document.getElementById('transcript-area');
    if (!area) return;

    if (!segments.length) {
      this.renderTranscriptPlaceholder(
        '◎',
        'Ready to transcribe',
        'Start a live capture or upload a recording to fill this studio with a searchable transcript.'
      );
      return;
    }

    area.innerHTML = segments.map((segment) => this.renderSegmentMarkup(segment)).join('');
    area.scrollTop = 0;
  },

  renderSegmentMarkup(segment) {
    const speakerNumber = (segment.speaker || '').replace('Speaker ', '') || '1';
    const speakerClass = `speaker-${speakerNumber}`;
    const confidence = this.formatConfidence(segment.confidence);
    const confidenceValue = Number(segment.confidence);
    const reviewSuggested = Number.isFinite(confidenceValue) && confidenceValue > 0 && confidenceValue < 0.62;
    const flags = [];

    if (segment.is_unclear) {
      flags.push('<span class="segment-flag warning">Unclear</span>');
    }

    if (reviewSuggested) {
      flags.push('<span class="segment-flag warning">Review</span>');
    }

    if (confidence !== 'n/a') {
      flags.push(`<span class="segment-flag">Confidence ${confidence}</span>`);
    }

    return `
      <article class="segment">
        <div class="segment-meta">
          <span class="segment-time">${this.formatTime(segment.start_time)}</span>
          <span class="segment-speaker ${speakerClass}">${this.escapeHtml(segment.speaker || 'Speaker 1')}</span>
          <span class="segment-confidence">${confidence === 'n/a' ? 'Confidence n/a' : `Confidence ${confidence}`}</span>
        </div>
        <div class="segment-body">
          <p class="segment-text ${segment.is_unclear ? 'unclear' : ''}">${this.highlightText(segment.text || '')}</p>
          ${flags.length ? `<div class="segment-flags">${flags.join('')}</div>` : ''}
        </div>
      </article>
    `;
  },

  renderTranscriptPlaceholder(icon, title, description) {
    const area = document.getElementById('transcript-area');
    if (!area) return;

    area.innerHTML = `
      <div class="transcript-empty">
        <div class="transcript-empty-icon">${this.escapeHtml(icon)}</div>
        <h3>${this.escapeHtml(title)}</h3>
        <p>${this.escapeHtml(description)}</p>
      </div>
    `;
  },

  renderSummary(data) {
    const summary = data?.summary || {};
    const stats = data?.stats || {};
    const note = document.getElementById('summary-note');
    const placeholder = document.getElementById('summary-placeholder');
    const content = document.getElementById('summary-content');

    document.getElementById('summary-text').textContent = summary.summary || 'No summary available.';

    if (note) {
      if (summary.note) {
        note.textContent = summary.note;
        note.classList.remove('hidden');
      } else {
        note.textContent = '';
        note.classList.add('hidden');
      }
    }

    this.renderList('summary-key-points', summary.key_points);
    this.renderList('summary-decisions', summary.decisions);
    this.renderList('summary-questions', summary.open_questions);
    this.renderActionItems('summary-actions', summary.action_items);

    document.getElementById('final-words').textContent = String(stats.word_count || this.getWordCount(this.segments));
    document.getElementById('final-speakers').textContent = String(stats.speaker_count || this.getSpeakerCount(this.segments));
    document.getElementById('final-unclear').textContent = String(stats.unclear_count || this.getUnclearCount(this.segments));

    placeholder?.classList.add('hidden');
    content?.classList.remove('hidden');
  },

  showSummaryPlaceholder(title, description, loading = false) {
    const placeholder = document.getElementById('summary-placeholder');
    const content = document.getElementById('summary-content');
    const titleEl = document.getElementById('summary-placeholder-title');
    const textEl = document.getElementById('summary-placeholder-text');
    const dots = document.getElementById('summary-loading-dots');
    const note = document.getElementById('summary-note');

    if (titleEl) titleEl.textContent = title;
    if (textEl) textEl.textContent = description;
    if (dots) dots.classList.toggle('hidden', !loading);
    if (note) {
      note.textContent = '';
      note.classList.add('hidden');
    }

    this.setText('final-words', '0');
    this.setText('final-speakers', '0');
    this.setText('final-unclear', '0');

    placeholder?.classList.remove('hidden');
    content?.classList.add('hidden');
  },

  renderList(elementId, items) {
    const element = document.getElementById(elementId);
    if (!element) return;

    if (!items || !items.length) {
      element.innerHTML = '<li class="summary-empty-item">None identified</li>';
      return;
    }

    element.innerHTML = items.map((item) => `<li>${this.escapeHtml(item)}</li>`).join('');
  },

  renderActionItems(elementId, items) {
    const element = document.getElementById(elementId);
    if (!element) return;

    if (!items || !items.length) {
      element.innerHTML = '<div class="summary-empty-item">None identified</div>';
      return;
    }

    element.innerHTML = items.map((item) => {
      if (typeof item === 'object' && item !== null) {
        return `
          <div class="action-item">
            <span class="action-task">${this.escapeHtml(item.task || '')}</span>
            <span class="action-owner">${this.escapeHtml(item.owner || 'Unassigned')}</span>
          </div>
        `;
      }

      return `
        <div class="action-item">
          <span class="action-task">${this.escapeHtml(item)}</span>
        </div>
      `;
    }).join('');
  },

  updateStats() {
    const words = this.getWordCount(this.segments);
    const segments = this.segments.length;
    const unclear = this.getUnclearCount(this.segments);
    const duration = this.getDuration();
    const confidence = this.getAverageConfidence();

    this.setText('stat-words', String(words));
    this.setText('stat-segments', String(segments));
    this.setText('stat-unclear', String(unclear));
    this.setText('stat-duration', this.formatTime(duration));
    this.setText('stat-confidence', confidence);
  },

  getWordCount(segments) {
    return segments.reduce((count, segment) => {
      const text = (segment.text || '').trim();
      if (!text || text.startsWith('[unclear')) return count;
      return count + text.split(/\s+/).length;
    }, 0);
  },

  getUnclearCount(segments) {
    return segments.filter((segment) => segment.is_unclear).length;
  },

  getSpeakerCount(segments) {
    const speakers = new Set(segments.map((segment) => segment.speaker).filter(Boolean));
    return speakers.size || (segments.length ? 1 : 0);
  },

  getDuration() {
    if (this.isRecording && this.startTime) {
      return Math.floor((Date.now() - this.startTime) / 1000);
    }

    return this.segments.reduce((max, segment) => {
      const endTime = Number(segment.end_time) || 0;
      return Math.max(max, endTime);
    }, 0);
  },

  getAverageConfidence() {
    const values = this.segments
      .map((segment) => Number(segment.confidence))
      .filter((value) => Number.isFinite(value) && value > 0);

    if (!values.length) return 'n/a';

    const average = values.reduce((sum, value) => sum + value, 0) / values.length;
    const percent = average <= 1 ? average * 100 : average;
    return `${Math.round(percent)}%`;
  },

  setActivity(mode, label, description) {
    const activity = document.getElementById('transcript-activity');
    const activityLabel = document.getElementById('activity-label');
    const activityMeta = document.getElementById('activity-meta');

    if (activity) activity.dataset.mode = mode;
    if (activityLabel) activityLabel.textContent = label;
    if (activityMeta) activityMeta.textContent = description;
  },

  setMeetingContext(title, subtitle) {
    this.activeMeetingTitle = title || '';

    const currentTitle = this.activeMeetingTitle || 'Ready to transcribe';
    const heroTitle = this.activeMeetingTitle || 'Ready for the next meeting';
    const heroSubtitle = subtitle || this.getIdleSubtitle();

    this.setText('current-meeting-title', currentTitle);
    this.setText('hero-meeting-title', heroTitle);
    this.setText('hero-meeting-subtitle', heroSubtitle);
    this.updateHeroSignals();
  },

  updateHeroSignals() {
    const recordingStatus = this.isRecording
      ? 'Recording live'
      : this.isLocalRecording
        ? 'Recording locally'
      : this.isUploading
        ? 'Processing file'
        : this.meetingId && this.segments.length
          ? 'Transcript loaded'
          : 'Idle';

    const mode = this.isRecording
      ? 'Live capture'
      : this.isLocalRecording
        ? 'Local recording'
        : this.isUploading
          ? 'Uploaded file'
        : this.activeMode === 'review'
          ? 'Reviewing meeting'
          : (this.capabilities.live_capture ? 'Live + file' : 'Upload only');

    const routeLabel = !this.capabilities.live_capture
      ? 'Uploads only'
      : this.audioDebugData?.capture_target === 'meeting_stream'
      ? 'Meeting stream'
      : this.audioDebugData?.capture_target === 'sink_monitor'
        ? 'Sink monitor'
        : 'Auto detect';

    this.setText('hero-status-text', recordingStatus);
    this.setText('hero-mode-text', mode);
    this.setText('hero-summary-text', this.summaryHealthLabel);
    this.setText('hero-route-text', routeLabel);
  },

  updateUI() {
    const startButton = document.getElementById('btn-start');
    const stopButton = document.getElementById('btn-stop');
    const inlineStart = document.getElementById('btn-start-inline');
    const inlineStop = document.getElementById('btn-stop-inline');
    const pauseButton = document.getElementById('btn-pause');
    const uploadButton = document.getElementById('btn-upload-audio');
    const recordingIndicator = document.getElementById('recording-indicator');
    const fileInput = document.getElementById('input-audio-file');
    const uploadTitle = document.getElementById('input-upload-title');
    const titleInput = document.getElementById('input-title');
    const systemSelect = document.getElementById('select-system-device');
    const micSelect = document.getElementById('select-mic-device');
    const micToggle = document.getElementById('toggle-mic');
    const copyButton = document.getElementById('btn-copy-transcript');
    const clearButton = document.getElementById('btn-clear-transcript');
    const clearSearchButton = document.getElementById('btn-clear-search');
    const exportButtons = document.querySelectorAll('[data-export]');
    const localStartButton = document.getElementById('btn-start-local-recording');
    const localStopButton = document.getElementById('btn-stop-local-recording');
    const localIndicator = document.getElementById('local-recording-indicator');
    const isBusy = this.isRecording || this.isUploading || this.isLocalRecording;
    const liveCaptureSupported = Boolean(this.capabilities.live_capture);
    const localRecordingSupported = Boolean(this.capabilities.local_recording);

    if (recordingIndicator) {
      recordingIndicator.classList.toggle('active', this.isRecording);
    }
    if (localIndicator) {
      localIndicator.classList.toggle('active', this.isLocalRecording);
    }

    if (startButton) {
      startButton.classList.toggle('hidden', this.isRecording);
      startButton.disabled = !liveCaptureSupported || this.isUploading || this.isLocalRecording;
      startButton.textContent = 'Start transcription';
    }

    if (stopButton) {
      stopButton.classList.toggle('hidden', !this.isRecording);
      stopButton.disabled = this.isUploading;
    }

    if (inlineStart) {
      inlineStart.disabled = !liveCaptureSupported || this.isRecording || this.isUploading || this.isLocalRecording;
      inlineStart.textContent = 'Start';
    }
    if (inlineStop) inlineStop.disabled = !liveCaptureSupported || !this.isRecording || this.isUploading;
    if (pauseButton) pauseButton.disabled = true;

    if (uploadButton) {
      uploadButton.disabled = this.isRecording || this.isUploading || this.isLocalRecording;
      uploadButton.textContent = this.isUploading ? 'Processing audio file...' : 'Transcribe audio file';
    }

    if (fileInput) fileInput.disabled = isBusy;
    if (uploadTitle) uploadTitle.disabled = isBusy;
    if (titleInput) titleInput.disabled = isBusy;
    if (systemSelect) systemSelect.disabled = isBusy || !liveCaptureSupported;
    if (micSelect) micSelect.disabled = isBusy || !liveCaptureSupported;
    if (micToggle) micToggle.disabled = isBusy || !liveCaptureSupported;

    if (localStartButton) {
      localStartButton.classList.toggle('hidden', this.isLocalRecording);
      localStartButton.disabled = !localRecordingSupported || this.isRecording || this.isUploading;
    }
    if (localStopButton) {
      localStopButton.classList.toggle('hidden', !this.isLocalRecording);
      localStopButton.disabled = !localRecordingSupported || this.isRecording || this.isUploading;
    }
    if (copyButton) copyButton.disabled = !this.segments.length;
    if (clearButton) clearButton.disabled = !this.segments.length || this.isRecording || this.isUploading || this.isLocalRecording;
    if (clearSearchButton) clearSearchButton.disabled = !this.searchQuery;

    const canExport = Boolean(this.meetingId) && !this.isRecording && !this.isUploading && !this.isLocalRecording;
    exportButtons.forEach((button) => {
      button.disabled = !canExport;
    });

    this.syncMicVisibility();
  },

  syncMicVisibility() {
    const micToggle = document.getElementById('toggle-mic');
    const micDeviceGroup = document.getElementById('mic-device-group');
    if (!micToggle || !micDeviceGroup) return;
    micDeviceGroup.style.display = this.capabilities.live_capture && micToggle.checked ? 'grid' : 'none';
  },

  startLocalRecordingTimer() {
    this.stopLocalRecordingTimer();
    this.setText('local-rec-timer', '00:00');
    this.localRecordingTimerInterval = window.setInterval(() => {
      const elapsedSeconds = Math.max(0, Math.floor((Date.now() - (this.localRecordingStartTime || Date.now())) / 1000));
      this.setText('local-rec-timer', this.formatTime(elapsedSeconds));
      this.setText('local-recording-file-size', this.formatTime(elapsedSeconds));
    }, 1000);
  },

  stopLocalRecordingTimer() {
    if (this.localRecordingTimerInterval) {
      window.clearInterval(this.localRecordingTimerInterval);
      this.localRecordingTimerInterval = null;
    }
  },

  updateLocalRecordingCard(details = {}) {
    if (this.isLocalRecording) {
      this.setText('local-recording-status', 'Recording system audio locally in the backend. No model is needed to save the WAV file.');
      return;
    }

    if (details.downloadUrl) {
      this.setText('local-rec-timer', this.formatTime(details.durationSeconds || 0));
      return;
    }

    this.setText('local-recording-status', 'Records system audio locally in the backend. No model is needed to save the WAV file.');
    this.setText('local-rec-timer', '00:00');
    this.setText('local-recording-file-pill', 'No recording yet');
    this.setText('local-recording-file-name', 'No local file yet');
    this.setText('local-recording-file-meta', 'Start and stop to save a backend WAV file that is ready to download.');
    this.setText('local-recording-file-size', '0 B');
  },

  startTimer() {
    this.stopTimer();
    this.timerInterval = window.setInterval(() => {
      this.setText('rec-timer', this.formatTime(this.getDuration()));
      this.setText('stat-duration', this.formatTime(this.getDuration()));
    }, 1000);
  },

  stopTimer() {
    if (this.timerInterval) {
      window.clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
  },

  onSearchInput(event) {
    this.searchQuery = (event?.target?.value || '').trim();
    this.renderTranscriptSegments(this.segments);
    this.updateSearchMetrics();
  },

  clearSearch() {
    this.searchQuery = '';
    const searchInput = document.getElementById('transcript-search');
    if (searchInput) searchInput.value = '';
    this.renderTranscriptSegments(this.segments);
    this.updateSearchMetrics();
    this.updateUI();
  },

  updateSearchMetrics() {
    const matches = this.searchQuery
      ? this.segments.reduce((count, segment) => count + this.countMatches(segment.text || '', this.searchQuery), 0)
      : 0;

    this.setText('transcript-match-count', `${matches} ${matches === 1 ? 'match' : 'matches'}`);
    this.setText('stat-matches', String(matches));
  },

  highlightText(text) {
    const safeText = String(text || '');
    if (!this.searchQuery) return this.escapeHtml(safeText);

    const query = this.searchQuery;
    const regex = new RegExp(`(${this.escapeRegExp(query)})`, 'ig');
    return safeText
      .split(regex)
      .map((part) => part.toLowerCase() === query.toLowerCase()
        ? `<mark class="transcript-match">${this.escapeHtml(part)}</mark>`
        : this.escapeHtml(part))
      .join('');
  },

  countMatches(text, query) {
    if (!query) return 0;
    const regex = new RegExp(this.escapeRegExp(query), 'ig');
    return (String(text || '').match(regex) || []).length;
  },

  handlePauseRequest() {
    this.showToast('Pause and resume will work once the backend exposes those controls.', 'info');
  },

  async copyTranscript() {
    if (!this.segments.length) {
      this.showToast('No transcript available to copy', 'error');
      return;
    }

    const transcriptText = this.segments.map((segment) => {
      const time = this.formatTime(segment.start_time);
      const speaker = segment.speaker || 'Speaker 1';
      return `[${time}] ${speaker}: ${segment.text || ''}`;
    }).join('\n');

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(transcriptText);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = transcriptText;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      this.showToast('Transcript copied to clipboard', 'success');
    } catch (error) {
      this.showToast('Could not copy transcript', 'error');
    }
  },

  clearWorkspace() {
    if (this.isRecording || this.isUploading) return;

    this.meetingId = null;
    this.segments = [];
    this.summaryData = null;
    this.activeMode = 'idle';
    this.searchQuery = '';

    const titleInput = document.getElementById('input-title');
    const uploadTitle = document.getElementById('input-upload-title');
    const fileInput = document.getElementById('input-audio-file');
    const searchInput = document.getElementById('transcript-search');

    if (titleInput) titleInput.value = '';
    if (uploadTitle) uploadTitle.value = '';
    if (fileInput) fileInput.value = '';
    if (searchInput) searchInput.value = '';

    this.setUploadState('empty');
    this.setMeetingContext('', this.getIdleSubtitle());
    this.renderTranscriptPlaceholder(
      '◎',
      'Ready to transcribe',
      this.getIdleTranscriptDescription()
    );
    this.showSummaryPlaceholder(
      'Summary ready when the transcript is complete',
      this.getIdleSummaryDescription(),
      false
    );
    this.setActivity('idle', 'Ready', 'The configured providers are idle and waiting for the next session.');
    this.updateStats();
    this.updateSearchMetrics();
    this.updateUI();
    this.loadHistory();
    this.onStatus('Transcript cleared from the current workspace.', 'info');
    this.showToast('Transcript cleared from view', 'info');
  },

  async viewMeeting(id) {
    try {
      const response = await this.apiFetch(`/api/meetings/${id}`);
      if (!response.ok) {
        throw new Error(await this.readErrorMessage(response));
      }
      const meeting = await response.json();

      this.meetingId = id;
      this.isRecording = false;
      this.isUploading = false;
      this.summaryData = null;
      this.stopTimer();
      this.startTime = null;
      this.activeMode = 'review';

      const titleInput = document.getElementById('input-title');
      const uploadTitle = document.getElementById('input-upload-title');
      if (titleInput) titleInput.value = meeting.title || '';
      if (uploadTitle) uploadTitle.value = meeting.title || '';

      this.segments = meeting.segments || [];
      this.setMeetingContext(meeting.title || 'Saved meeting', 'Viewing a saved meeting from the meeting library.');
      this.renderTranscriptSegments(this.segments);
      this.updateStats();
      this.updateSearchMetrics();
      this.updateUI();

      this.stopAudioDebugPolling();
      if (this.capabilities.live_capture) {
        this.loadAudioDebug();
      }

      if (meeting.summary) {
        this.renderSummary({
          summary: {
            summary: meeting.summary,
            key_points: meeting.key_points || [],
            decisions: meeting.decisions || [],
            action_items: meeting.action_items || [],
            open_questions: meeting.open_questions || [],
            note: '',
          },
          stats: {
            word_count: meeting.word_count,
            speaker_count: meeting.speaker_count,
            unclear_count: meeting.unclear_count,
          },
        });
      } else {
        this.showSummaryPlaceholder(
          'No summary stored for this meeting',
          'Transcript loaded successfully, but the meeting has no saved summary.',
          false
        );
      }

      this.setActivity('review', 'Viewing saved meeting', 'You can search, copy, or export the loaded meeting.');
      this.onStatus(`Loaded meeting: ${meeting.title || 'Untitled Meeting'}`, 'success');
      this.loadHistory();
    } catch (error) {
      this.showToast('Failed to load meeting', 'error');
    }
  },

  async deleteMeeting(id) {
    if (!window.confirm('Delete this meeting and all its data?')) return;

    try {
      const response = await this.apiFetch(`/api/meetings/${id}`, { method: 'DELETE' });
      if (!response.ok) {
        throw new Error(await this.readErrorMessage(response));
      }

      if (this.meetingId === id) {
        this.clearWorkspace();
      } else {
        this.loadHistory();
      }

      this.showToast('Meeting deleted', 'success');
    } catch (error) {
      this.showToast(error.message || 'Failed to delete meeting', 'error');
    }
  },

  handleExport(button) {
    const [type, format] = button.dataset.export.split('-');

    if (!this.meetingId) {
      this.showToast('Load or finish a meeting before exporting', 'error');
      return;
    }

    if (type === 'transcript') {
      ExportManager.downloadTranscript(this.meetingId, format);
      return;
    }

    ExportManager.downloadSummary(this.meetingId, format);
  },

  handleKeyboardShortcuts(event) {
    if (!this.isAuthenticated) return;

    const isModifier = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();

    if (isModifier && event.key === 'Enter') {
      event.preventDefault();
      if (!this.isRecording && !this.isUploading) {
        this.startRecording();
      }
      return;
    }

    if (event.key === 'Escape') {
      if (this.isRecording) {
        event.preventDefault();
        this.stopRecording();
      }
      return;
    }

    if (isModifier && key === 'f') {
      event.preventDefault();
      const search = document.getElementById('transcript-search');
      search?.focus();
      search?.select();
    }
  },

  setUploadState(state, details = {}) {
    const pill = document.getElementById('upload-status-pill');
    const name = document.getElementById('audio-file-name');
    const size = document.getElementById('audio-file-size');
    const note = document.getElementById('audio-file-meta');
    const track = document.getElementById('upload-progress-track');
    const fill = document.getElementById('upload-progress-fill');

    if (!pill || !name || !size || !note || !track || !fill) return;

    pill.className = 'soft-pill';
    track.classList.remove('indeterminate');
    fill.style.width = '0%';

    if (state === 'empty') {
      pill.textContent = 'No file selected';
      name.textContent = 'No file selected';
      size.textContent = '0 B';
      note.textContent = 'Choose an audio recording to run a full-pass transcription with the configured backend pipeline.';
      return;
    }

    name.textContent = details.name || 'Selected file';
    size.textContent = this.formatBytes(details.size || 0);
    note.textContent = details.note || '';

    if (state === 'selected') {
      pill.textContent = 'Ready to process';
      pill.classList.add('active');
      fill.style.width = '100%';
      return;
    }

    if (state === 'working') {
      pill.textContent = 'Processing file';
      pill.classList.add('working');
      track.classList.add('indeterminate');
      return;
    }

    if (state === 'success') {
      pill.textContent = 'Complete';
      pill.classList.add('success');
      fill.style.width = '100%';
      return;
    }

    if (state === 'error') {
      pill.textContent = 'Failed';
      pill.classList.add('error');
      fill.style.width = '100%';
    }
  },

  setUploadHelperText(message, state = '') {
    const helper = document.getElementById('upload-helper-text');
    if (!helper) return;

    helper.textContent = message;
    helper.className = 'upload-helper';
    if (state) helper.classList.add(state);
  },

  ensureMeetingTitle(prefix) {
    const titleInput = document.getElementById('input-title');
    const rawTitle = titleInput?.value.trim();
    const title = rawTitle || this.generateMeetingTitle(prefix);
    if (titleInput && !rawTitle) titleInput.value = title;
    return title;
  },

  generateMeetingTitle(prefix = 'Meeting') {
    const now = new Date();
    const datePart = now.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
    const timePart = now.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    });
    return `${prefix} · ${datePart} · ${timePart}`;
  },

  resolveToneFromMessage(message) {
    const normalized = String(message || '').toLowerCase();
    if (normalized.includes('failed') || normalized.includes('error') || normalized.includes('not found')) return 'error';
    if (normalized.includes('complete') || normalized.includes('ready') || normalized.includes('started')) return 'success';
    return 'info';
  },

  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    window.setTimeout(() => toast.remove(), 4200);
  },

  async readErrorMessage(response) {
    try {
      const payload = await response.json();
      return payload.detail || payload.message || `Request failed with status ${response.status}`;
    } catch (error) {
      return `Request failed with status ${response.status}`;
    }
  },

  formatTime(seconds) {
    const safeSeconds = Math.floor(Number(seconds) || 0);
    const hours = Math.floor(safeSeconds / 3600);
    const minutes = Math.floor((safeSeconds % 3600) / 60);
    const remainingSeconds = safeSeconds % 60;

    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
    }

    return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
  },

  formatDateTime(value) {
    if (!value) return 'Unknown date';
    const date = new Date(value);
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  },

  formatConfidence(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return 'n/a';
    const percent = numeric <= 1 ? numeric * 100 : numeric;
    return `${Math.round(percent)}%`;
  },

  formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes;
    let unitIndex = 0;

    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }

    return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  },

  setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  },

  getIdleSubtitle() {
    return this.capabilities.live_capture
      ? 'Capture live meetings or upload a recording to begin a transcription session.'
      : 'Upload an audio or meeting recording file to begin a transcription session.';
  },

  getIdleTranscriptDescription() {
    return this.capabilities.live_capture
      ? 'Start a live capture or upload a recording to fill this studio with a searchable transcript.'
      : 'Upload a recording to fill this studio with a searchable transcript.';
  },

  getIdleSummaryDescription() {
    return this.capabilities.live_capture
      ? 'Stop a live session or finish an uploaded file to generate key points, action items, decisions, and follow-ups.'
      : 'Finish an uploaded file to generate key points, action items, decisions, and follow-ups.';
  },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
