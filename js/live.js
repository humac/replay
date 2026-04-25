// Live stream view — polls status, attaches HLS.js on the LL-HLS proxy,
// shows an offline placeholder otherwise, and tears down cleanly on exit.

const LIVE_POLL_INTERVAL_MS = 4000;
const LIVE_HLS_URL = '/api/live/hls/index.m3u8';

export const liveMixin = {
    showLiveView({ pushHistory = true, replaceHistory = false, scrollTop = true } = {}) {
        this.teardownGameView();
        this.activateView('live-view', 'live');

        const settings = this.getAppSettings();
        const placeholderLabel = document.getElementById('live-placeholder-label');
        if (placeholderLabel) placeholderLabel.textContent = settings.live_offline_message || 'No live stream right now.';

        if (settings.live_enabled !== '1') {
            this.applyLiveStatus({ enabled: false, active: false, ready: false });
        } else {
            this.applyLiveStatus({ enabled: true, active: false, ready: false });
            this.refreshLiveStatus();
            this.startLiveStatusPolling();
        }

        if (pushHistory) {
            this.pushHistoryState({ view: 'live' }, { replace: replaceHistory, url: '/live' });
        }
        if (scrollTop) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    teardownLiveView() {
        if (this.liveStatusTimer) {
            clearInterval(this.liveStatusTimer);
            this.liveStatusTimer = null;
        }
        this.detachLivePlayer();
        this.liveLastActive = false;
    },

    startLiveStatusPolling() {
        if (this.liveStatusTimer) return;
        this.liveStatusTimer = setInterval(() => {
            this.refreshLiveStatus();
        }, LIVE_POLL_INTERVAL_MS);
    },

    async refreshLiveStatus() {
        try {
            const resp = await fetch('/api/live/status', { cache: 'no-store' });
            if (!resp.ok) {
                this.applyLiveStatus({ enabled: true, active: false, ready: false });
                return;
            }
            const data = await resp.json();
            this.applyLiveStatus(data);
        } catch {
            this.applyLiveStatus({ enabled: true, active: false, ready: false });
        }
    },

    applyLiveStatus(status) {
        const badge = document.getElementById('live-status-badge');
        const text = document.getElementById('live-status-text');
        const placeholder = document.getElementById('live-placeholder');
        const placeholderSub = document.getElementById('live-placeholder-sub');
        const video = document.getElementById('live-video');
        const metaRow = document.getElementById('live-meta-row');

        const enabled = status?.enabled !== false;
        const isActive = !!(status?.active && status?.ready);

        if (badge) {
            badge.dataset.state = !enabled ? 'disabled' : (isActive ? 'live' : 'offline');
        }
        if (text) {
            text.textContent = !enabled ? 'Disabled' : (isActive ? 'LIVE' : 'Offline');
        }

        if (!enabled) {
            this.detachLivePlayer();
            if (placeholder) placeholder.style.display = 'flex';
            if (placeholderSub) placeholderSub.textContent = 'Live streaming is currently disabled in settings.';
            if (video) video.style.display = 'none';
            if (metaRow) metaRow.style.display = 'none';
            return;
        }

        if (isActive) {
            if (placeholder) placeholder.style.display = 'none';
            if (video) video.style.display = '';
            if (metaRow) metaRow.style.display = 'flex';
            if (!this.liveLastActive) this.attachLivePlayer();
            this.liveLastActive = true;
        } else {
            if (this.liveLastActive) this.detachLivePlayer();
            this.liveLastActive = false;
            if (placeholder) placeholder.style.display = 'flex';
            const settings = this.getAppSettings();
            if (placeholderSub) {
                placeholderSub.textContent = status?.reachable === false
                    ? 'Streaming server is unreachable. Try again in a moment.'
                    : (settings.live_offline_message
                        ? 'Check back at kick-off — the feed will start automatically.'
                        : 'The feed will start automatically when the camera goes online.');
            }
            if (video) {
                video.style.display = 'none';
                video.removeAttribute('src');
                video.load?.();
            }
            if (metaRow) metaRow.style.display = 'none';
        }
    },

    attachLivePlayer() {
        const video = document.getElementById('live-video');
        if (!video) return;

        // Native HLS (Safari, iOS) — let the browser handle it.
        if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = LIVE_HLS_URL;
            const onLoaded = () => {
                video.play?.().catch(() => {});
                video.removeEventListener('loadedmetadata', onLoaded);
            };
            video.addEventListener('loadedmetadata', onLoaded);
            return;
        }

        if (typeof Hls === 'undefined' || !Hls.isSupported?.()) {
            console.warn('HLS.js not available; live stream cannot be played in this browser.');
            return;
        }

        if (this.liveHls) {
            try { this.liveHls.destroy(); } catch { /* ignore */ }
            this.liveHls = null;
        }

        const hls = new Hls({
            lowLatencyMode: true,
            backBufferLength: 30,
            liveSyncDuration: 2,
            liveMaxLatencyDuration: 6,
            enableWorker: true,
        });
        hls.loadSource(LIVE_HLS_URL);
        hls.attachMedia(video);
        hls.on(Hls.Events.ERROR, (_event, data) => {
            if (data.fatal) {
                console.warn('Fatal HLS error on live stream:', data);
                this.detachLivePlayer();
                this.liveLastActive = false;
            }
        });
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
            video.play?.().catch(() => {});
        });
        this.liveHls = hls;
    },

    detachLivePlayer() {
        const video = document.getElementById('live-video');
        if (this.liveHls) {
            try { this.liveHls.destroy(); } catch { /* ignore */ }
            this.liveHls = null;
        }
        if (video) {
            try { video.pause(); } catch { /* ignore */ }
            video.removeAttribute('src');
            try { video.load(); } catch { /* ignore */ }
        }
    },

    // ===== ADMIN: Live Settings card =====

    async loadLiveAdminConfig() {
        try {
            const resp = await fetch('/api/admin/live/config', { headers: this.getAuthHeaders() });
            if (!resp.ok) throw new Error('Failed to load live config');
            return await resp.json();
        } catch (e) {
            console.warn('loadLiveAdminConfig failed:', e);
            return null;
        }
    },

    async renderLiveSettingsCard() {
        const card = document.getElementById('live-settings-card');
        if (!card) return;
        if (!this.isAdmin()) {
            card.style.display = 'none';
            return;
        }
        card.style.display = 'block';

        const settings = this.getAppSettings();
        const enabledEl = document.getElementById('settings-live-enabled');
        const rtmpEl = document.getElementById('settings-live-rtmp-public-url');
        const navLabelEl = document.getElementById('settings-nav-live-label');
        const offlineEl = document.getElementById('settings-live-offline-message');
        if (enabledEl) enabledEl.checked = settings.live_enabled === '1';
        if (rtmpEl) rtmpEl.value = settings.live_rtmp_public_url || '';
        if (navLabelEl) navLabelEl.value = settings.nav_live_label || '';
        if (offlineEl) offlineEl.value = settings.live_offline_message || '';

        const config = await this.loadLiveAdminConfig();
        this._liveAdminConfig = config;
        const rtmpDisplay = document.getElementById('live-config-rtmp');
        if (rtmpDisplay) {
            const base = (settings.live_rtmp_public_url || '').replace(/\/+$/, '');
            rtmpDisplay.textContent = base
                ? `${base}/${config?.stream_key || '<stream-key>'}`
                : 'Set the public RTMP URL above to see the full endpoint.';
        }
        const keyDisplay = document.getElementById('live-config-stream-key');
        if (keyDisplay) {
            keyDisplay.textContent = '••••••••';
            keyDisplay.dataset.revealed = '';
            keyDisplay.dataset.value = config?.stream_key || '';
        }

        this.bindLiveSettingsActionsOnce();
    },

    bindLiveSettingsActionsOnce() {
        if (this._liveSettingsBound) return;
        this._liveSettingsBound = true;

        document.getElementById('live-reveal-key-btn')?.addEventListener('click', () => {
            const el = document.getElementById('live-config-stream-key');
            if (!el) return;
            const isRevealed = el.dataset.revealed === '1';
            if (isRevealed) {
                el.textContent = '••••••••';
                el.dataset.revealed = '';
                document.getElementById('live-reveal-key-btn').textContent = 'Reveal';
            } else {
                el.textContent = el.dataset.value || '(none)';
                el.dataset.revealed = '1';
                document.getElementById('live-reveal-key-btn').textContent = 'Hide';
            }
        });

        document.getElementById('live-copy-key-btn')?.addEventListener('click', () => {
            const el = document.getElementById('live-config-stream-key');
            const value = el?.dataset.value || '';
            if (!value) return this.showError('No stream key configured yet.');
            navigator.clipboard?.writeText(value).then(
                () => this.showSuccess('Stream key copied.'),
                () => this.showError('Could not access clipboard.'),
            );
        });

        document.getElementById('live-copy-rtmp-btn')?.addEventListener('click', () => {
            const el = document.getElementById('live-config-rtmp');
            const value = el?.textContent?.trim() || '';
            if (!value || value.startsWith('Set the public')) {
                return this.showError('Set the public RTMP URL first, then save.');
            }
            navigator.clipboard?.writeText(value).then(
                () => this.showSuccess('RTMP endpoint copied.'),
                () => this.showError('Could not access clipboard.'),
            );
        });

        document.getElementById('live-rotate-key-btn')?.addEventListener('click', async () => {
            if (!confirm('Rotate the live stream key? Any camera using the current key will be disconnected.')) return;
            const btn = document.getElementById('live-rotate-key-btn');
            const restore = this.btnLoading(btn, 'Rotating...');
            try {
                const resp = await fetch('/api/admin/live/rotate-key', {
                    method: 'POST',
                    headers: this.getAuthHeaders(),
                });
                if (!resp.ok) throw new Error('Failed to rotate key');
                const data = await resp.json();
                this._liveAdminConfig = { ...(this._liveAdminConfig || {}), stream_key: data.stream_key };
                const keyEl = document.getElementById('live-config-stream-key');
                if (keyEl) {
                    keyEl.textContent = data.stream_key;
                    keyEl.dataset.value = data.stream_key;
                    keyEl.dataset.revealed = '1';
                    const reveal = document.getElementById('live-reveal-key-btn');
                    if (reveal) reveal.textContent = 'Hide';
                }
                const rtmpDisplay = document.getElementById('live-config-rtmp');
                const settings = this.getAppSettings();
                if (rtmpDisplay && settings.live_rtmp_public_url) {
                    const base = settings.live_rtmp_public_url.replace(/\/+$/, '');
                    rtmpDisplay.textContent = `${base}/${data.stream_key}`;
                }
                this.showSuccess('Stream key rotated.');
            } catch (e) {
                this.showError(e.message);
            } finally {
                restore('Rotate');
            }
        });
    },
};
