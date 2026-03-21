// Chunked upload session management.

export const uploadsMixin = {
    async uploadFileIfSelected(inputId, matchId, type, param) {
        const input = document.getElementById(inputId);
        if (!input || !input.files[0]) return;

        const form = new FormData();
        form.append('file', input.files[0]);

        const url = type === 'logo'
            ? `/api/matches/${matchId}/upload-logo?team=${param}`
            : `/api/matches/${matchId}/upload-video?slot=${param}`;

        const resp = await fetch(url, { method: 'POST', body: form, headers: this.getAuthHeaders() });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `Upload failed for ${inputId}`);
        }
    },

    async uploadVideoIfSelected(inputId, matchId, slot) {
        const input = document.getElementById(inputId);
        if (!input || !input.files[0]) return;

        const file = input.files[0];
        const uploadKey = this.getUploadSessionKey(matchId, slot, file);

        let progressKey;
        if (slot === 'full') progressKey = 'full';
        else if (slot === 'first_half') progressKey = 'first';
        else progressKey = 'second';

        const pEl = document.getElementById('progress-' + progressKey);
        const fEl = document.getElementById('progress-fill-' + progressKey);
        const tEl = document.getElementById('progress-text-' + progressKey);

        if (pEl) pEl.style.display = 'flex';
        if (fEl) {
            fEl.classList.add('indeterminate');
            fEl.style.width = '35%';
        }
        if (tEl) tEl.textContent = 'Uploading...';

        let session = this.getSavedUploadSession(uploadKey);
        if (session?.session_id) {
            const existing = await this.fetchUploadSession(session.session_id);
            if (existing && existing.status === 'active' && existing.match_id === matchId && existing.slot === slot && existing.size_bytes === file.size) {
                session = existing;
            } else {
                this.clearSavedUploadSession(uploadKey);
                session = null;
            }
        }

        if (!session) {
            const sessionResp = await fetch(`/api/matches/${matchId}/upload-video/session?slot=${slot}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders() },
                body: JSON.stringify({ filename: file.name, size_bytes: file.size }),
            });
            if (!sessionResp.ok) {
                const err = await sessionResp.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to start upload session');
            }
            session = await sessionResp.json();
            this.saveUploadSession(uploadKey, {
                session_id: session.session_id,
                match_id: matchId,
                slot,
                size_bytes: file.size,
                file_name: file.name,
                updated_at: Date.now(),
            });
        }

        const { session_id, chunk_size, total_chunks } = session;
        let nextIndex = session.next_index || 0;
        let uploadedBytes = Math.min(file.size, nextIndex * chunk_size);

        if (fEl) fEl.classList.remove('indeterminate');
        if (fEl) fEl.style.width = `${Math.round((uploadedBytes / file.size) * 100)}%`;
        if (tEl) {
            if (nextIndex > 0) {
                tEl.textContent = `Resuming at chunk ${nextIndex + 1}/${total_chunks}`;
            } else {
                tEl.textContent = '0%';
            }
        }

        if (nextIndex >= total_chunks) {
            await this.completeUploadSession(session_id, uploadKey, fEl, tEl);
            return;
        }

        for (let index = nextIndex; index < total_chunks; index++) {
            const start = index * chunk_size;
            const end = Math.min(file.size, start + chunk_size);
            const chunk = file.slice(start, end);

            let lastErr = null;
            for (let attempt = 1; attempt <= this.CHUNK_RETRY_COUNT; attempt++) {
                try {
                    const chunkResp = await fetch(`/api/uploads/sessions/${session_id}/chunk?index=${index}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/octet-stream', ...this.getAuthHeaders() },
                        body: chunk,
                    });

                    if (!chunkResp.ok) {
                        const err = await chunkResp.json().catch(() => ({}));
                        throw new Error(err.detail || `Chunk ${index + 1} failed`);
                    }

                    uploadedBytes = end;
                    nextIndex = index + 1;
                    this.saveUploadSession(uploadKey, {
                        session_id,
                        match_id: matchId,
                        slot,
                        size_bytes: file.size,
                        file_name: file.name,
                        updated_at: Date.now(),
                    });
                    if (fEl && tEl) {
                        const pct = Math.round((uploadedBytes / file.size) * 100);
                        fEl.style.width = pct + '%';
                        tEl.textContent = `${pct}% (${index + 1}/${total_chunks} chunks)`;
                    }
                    lastErr = null;
                    break;
                } catch (err) {
                    lastErr = err;
                    if (tEl) tEl.textContent = `Retrying chunk ${index + 1}/${total_chunks} (${attempt}/${this.CHUNK_RETRY_COUNT})...`;
                    if (attempt < this.CHUNK_RETRY_COUNT) {
                        await new Promise((r) => setTimeout(r, 600 * attempt));
                    }
                }
            }

            if (lastErr) {
                throw lastErr;
            }
        }

        await this.completeUploadSession(session_id, uploadKey, fEl, tEl);
    },

    async completeUploadSession(sessionId, uploadKey, fEl, tEl) {
        const completeResp = await fetch(`/api/uploads/sessions/${sessionId}/complete`, {
            method: 'POST',
            headers: this.getAuthHeaders(),
        });
        if (!completeResp.ok) {
            const err = await completeResp.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to complete upload session');
        }

        if (fEl) fEl.style.width = '100%';
        if (tEl) tEl.textContent = 'Uploaded - processing';
        this.clearSavedUploadSession(uploadKey);
    },

    getUploadSessionKey(matchId, slot, file) {
        return [matchId, slot, file.name, file.size, file.lastModified].join('::');
    },

    getSavedUploadSessions() {
        try {
            return JSON.parse(localStorage.getItem(this.UPLOAD_SESSION_STORAGE_KEY) || '{}');
        } catch {
            return {};
        }
    },

    getSavedUploadSession(key) {
        const sessions = this.getSavedUploadSessions();
        return sessions[key] || null;
    },

    saveUploadSession(key, sessionData) {
        const sessions = this.getSavedUploadSessions();
        sessions[key] = sessionData;
        localStorage.setItem(this.UPLOAD_SESSION_STORAGE_KEY, JSON.stringify(sessions));
    },

    clearSavedUploadSession(key) {
        const sessions = this.getSavedUploadSessions();
        if (!sessions[key]) return;
        delete sessions[key];
        localStorage.setItem(this.UPLOAD_SESSION_STORAGE_KEY, JSON.stringify(sessions));
    },

    clearSavedUploadSessionBySessionId(sessionId) {
        const sessions = this.getSavedUploadSessions();
        Object.entries(sessions).forEach(([key, value]) => {
            if (value.session_id === sessionId) {
                delete sessions[key];
            }
        });
        localStorage.setItem(this.UPLOAD_SESSION_STORAGE_KEY, JSON.stringify(sessions));
    },

    async fetchUploadSession(sessionId) {
        try {
            const resp = await fetch(`/api/uploads/sessions/${sessionId}`, {
                headers: this.getAuthHeaders(),
            });
            if (!resp.ok) return null;
            return await resp.json();
        } catch {
            return null;
        }
    },

    resetFileLabels() {
        ['f-home-logo', 'f-away-logo', 'f-video-full', 'f-video-first', 'f-video-second'].forEach(id => {
            const label = document.getElementById(id + '-label');
            if (label) label.textContent = 'No file chosen';
            const input = document.getElementById(id);
            if (input) input.value = '';
        });
        ['full', 'first', 'second'].forEach(key => {
            const pEl = document.getElementById('progress-' + key);
            const fEl = document.getElementById('progress-fill-' + key);
            if (pEl) pEl.style.display = 'none';
            if (fEl) fEl.style.width = '0%';
        });
        ['f-home-logo-state', 'f-away-logo-state', 'f-video-full-state', 'f-video-first-state', 'f-video-second-state'].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.className = 'uploaded-state';
        });
        document.getElementById('f-home-logo-state').textContent = 'No logo uploaded yet.';
        document.getElementById('f-away-logo-state').textContent = 'No logo uploaded yet.';
        document.getElementById('f-video-full-state').textContent = 'No video uploaded yet.';
        document.getElementById('f-video-first-state').textContent = 'No video uploaded yet.';
        document.getElementById('f-video-second-state').textContent = 'No video uploaded yet.';
    },
};
