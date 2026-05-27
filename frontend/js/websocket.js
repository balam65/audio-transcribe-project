/**
 * WebSocket Client for Meeting Transcription
 * Handles connection, reconnection, and message routing.
 */

class TranscriptionWebSocket {
  constructor(onSegment, onStatus, onSummary, onError, onConnectionChange, onSessionStarted) {
    this.ws = null;
    this.onSegment = onSegment;
    this.onStatus = onStatus;
    this.onSummary = onSummary;
    this.onError = onError;
    this.onConnectionChange = onConnectionChange;
    this.onSessionStarted = onSessionStarted;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 2000;
    this.manualClose = false;
  }

  connect() {
    this.manualClose = false;
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/api/transcription/ws`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.onConnectionChange('connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case 'segment':
            this.onSegment(msg.data);
            break;
          case 'status':
            this.onStatus(msg.message);
            break;
          case 'summary':
            this.onSummary(msg.data);
            break;
          case 'session_started':
            if (this.onSessionStarted) this.onSessionStarted(msg.data);
            break;
          case 'error':
            this.onError(msg.message);
            break;
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    this.ws.onclose = () => {
      this.onConnectionChange('disconnected');
      if (!this.manualClose) {
        this._tryReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      return true;
    }
    return false;
  }

  startTranscription(options) {
    return this.send({
      action: 'start',
      title: options.title || 'Untitled Meeting',
      system_audio: options.systemAudio !== false,
      mic_audio: options.micAudio === true,
      system_device_index: options.systemDeviceIndex ?? null,
      mic_device_index: options.micDeviceIndex ?? null,
    });
  }

  stopTranscription() {
    return this.send({ action: 'stop' });
  }

  _tryReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      setTimeout(() => this.connect(), this.reconnectDelay * this.reconnectAttempts);
    }
  }

  disconnect() {
    if (this.ws) {
      this.manualClose = true;
      this.ws.close();
      this.ws = null;
    }
  }
}

// Export for use in app.js
window.TranscriptionWebSocket = TranscriptionWebSocket;
