/**
 * Export utility functions for downloading transcripts and summaries.
 */

const ExportManager = {
  /**
   * Download a transcript export from the server.
   * @param {string} meetingId
   * @param {string} format - txt, md, docx, pdf
   */
  async downloadTranscript(meetingId, format) {
    try {
      const url = `/api/export/transcript/${meetingId}/${format}`;
      await this._download(url, `transcript.${format}`);
    } catch (e) {
      console.error('Export failed:', e);
      App.showToast('Export failed: ' + e.message, 'error');
    }
  },

  /**
   * Download a summary export from the server.
   * @param {string} meetingId
   * @param {string} format - txt, md, docx, pdf
   */
  async downloadSummary(meetingId, format) {
    try {
      const url = `/api/export/summary/${meetingId}/${format}`;
      await this._download(url, `summary.${format}`);
    } catch (e) {
      console.error('Export failed:', e);
      App.showToast('Export failed: ' + e.message, 'error');
    }
  },

  async _download(url, fallbackName) {
    const response = await fetch(url);
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || 'Export failed');
    }

    const blob = await response.blob();

    // Get filename from Content-Disposition header if available
    const disposition = response.headers.get('Content-Disposition');
    let filename = fallbackName;
    if (disposition) {
      const match = disposition.match(/filename="?([^";\n]+)"?/);
      if (match) filename = match[1];
    }

    // Trigger browser download
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);

    App.showToast(`Exported: ${filename}`, 'success');
  }
};

window.ExportManager = ExportManager;
