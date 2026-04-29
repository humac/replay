// Playback, AirPlay, Chromecast, and QoL methods.

const POSITION_STORAGE_KEY = 'replay_playback_positions';
const SPEED_STORAGE_KEY = 'replay_playback_speed';
const POSITION_SAVE_INTERVAL = 3; // seconds between saves
const POSITION_RESUME_THRESHOLD = 5; // ignore if < 5s from start
const POSITION_END_MARGIN = 30; // ignore if < 30s from end

export const playerMixin = {
    // ===== AIRPLAY =====
    initAirPlay() {
        const videoEl = document.getElementById('game-video');
        const airplayBtn = document.getElementById('airplay-btn');
        if (!videoEl || !airplayBtn) return;

        videoEl.disableRemotePlayback = false;

        const refreshAvailability = (available) => {
            this.airplayAvailable = available;
            airplayBtn.style.display = available ? 'flex' : 'none';
            this.updateRemotePlaybackNote();
        };

        if (typeof videoEl.webkitShowPlaybackTargetPicker === 'function') {
            refreshAvailability(true);
            videoEl.addEventListener('webkitplaybacktargetavailabilitychanged', (event) => {
                refreshAvailability(event.availability === 'available');
            });
            videoEl.addEventListener('webkitcurrentplaybacktargetiswirelesschanged', () => {
                this.airplayActive = !!videoEl.webkitCurrentPlaybackTargetIsWireless;
                airplayBtn.classList.toggle('casting', this.airplayActive);
                this.updateRemotePlaybackNote();
            });
            return;
        }

        if (videoEl.remote && typeof videoEl.remote.watchAvailability === 'function') {
            videoEl.remote.watchAvailability((available) => {
                refreshAvailability(!!available);
            }).catch(() => {
                refreshAvailability(false);
            });
        }
    },

    // ===== CHROMECAST =====
    initCast() {
        const castBtn = document.getElementById('cast-btn');
        this.castSupportedBrowser = this.isCastSupportedBrowser();
        this.castSecureContextAllowed = this.isCastSecureContextAllowed();
        if (castBtn) {
            castBtn.style.display = this.castSupportedBrowser ? 'flex' : 'none';
            castBtn.classList.toggle('remote-playback-btn-disabled', this.castSupportedBrowser);
        }

        const bootstrap = window.__replayCastBootstrap;
        if (bootstrap && Array.isArray(bootstrap.listeners)) {
            bootstrap.listeners.push((isAvailable) => {
                this.setupCastFramework(isAvailable);
            });
        }

        if (typeof bootstrap?.available === 'boolean') {
            this.setupCastFramework(bootstrap.available);
            return;
        }

        if (window.cast?.framework && window.chrome?.cast) {
            this.setupCastFramework(true);
        } else {
            this.retryCastFrameworkDetection();
            this.updateRemotePlaybackNote();
        }
    },

    isCastSupportedBrowser() {
        const ua = navigator.userAgent || '';
        return /(Chrome|Chromium|CriOS|Edg)\//.test(ua) && !/OPR\//.test(ua);
    },

    isCastSecureContextAllowed() {
        if (window.isSecureContext) return true;
        const hostname = window.location.hostname || '';
        return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
    },

    retryCastFrameworkDetection() {
        if (!this.castSupportedBrowser) return;
        window.setTimeout(() => {
            if (window.cast?.framework && window.chrome?.cast) {
                this.setupCastFramework(true);
                return;
            }
            this.updateRemotePlaybackNote();
        }, 1500);
    },

    setupCastFramework(isAvailable) {
        this.castAvailable = !!isAvailable;
        this.castSdkReady = !!isAvailable && !!window.cast?.framework && !!window.chrome?.cast;

        const castBtns = ['cast-btn', 'cast-btn-live']
            .map((id) => document.getElementById(id))
            .filter(Boolean);
        if (!isAvailable || !window.cast?.framework || !window.chrome?.cast) {
            if (this.castSupportedBrowser) {
                castBtns.forEach((btn) => {
                    btn.style.display = 'flex';
                    btn.classList.add('remote-playback-btn-disabled');
                });
            }
            this.updateRemotePlaybackNote();
            return;
        }

        castBtns.forEach((btn) => {
            btn.style.display = 'flex';
            btn.classList.remove('remote-playback-btn-disabled');
        });

        if (this._castInitialized) {
            this.updateRemotePlaybackNote();
            return;
        }

        const castContext = cast.framework.CastContext.getInstance();
        castContext.setOptions({
            receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
            autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
        });

        castContext.addEventListener(
            cast.framework.CastContextEventType.SESSION_STATE_CHANGED,
            (event) => {
                if (event.sessionState === cast.framework.SessionState.SESSION_STARTED ||
                    event.sessionState === cast.framework.SessionState.SESSION_RESUMED) {
                    this.onCastConnected();
                } else if (event.sessionState === cast.framework.SessionState.SESSION_ENDED) {
                    this.onCastDisconnected();
                }
            }
        );

        this._castInitialized = true;
        this.updateRemotePlaybackNote();
    },

    toggleCast() {
        if (!this.castSupportedBrowser || !this.castSecureContextAllowed || !window.cast?.framework) {
            this.updateRemotePlaybackNote();
            return;
        }

        if (this.castSession) {
            cast.framework.CastContext.getInstance().endCurrentSession(true);
        } else {
            cast.framework.CastContext.getInstance().requestSession().catch(() => {
                this.updateRemotePlaybackNote();
            });
        }
    },

    async toggleAirPlay() {
        const videoEl = document.getElementById('game-video');
        if (!videoEl) return;

        if (typeof videoEl.webkitShowPlaybackTargetPicker === 'function') {
            videoEl.webkitShowPlaybackTargetPicker();
            return;
        }

        if (videoEl.remote && typeof videoEl.remote.prompt === 'function') {
            try {
                await videoEl.remote.prompt();
            } catch {
                // Ignore user-cancelled prompt
            }
        }
    },

    onCastConnected() {
        this.castSession = cast.framework.CastContext.getInstance().getCurrentSession();
        const castBtns = ['cast-btn', 'cast-btn-live']
            .map((id) => document.getElementById(id))
            .filter(Boolean);
        castBtns.forEach((btn) => btn.classList.add('casting'));

        const deviceName = this.castSession.getCastDevice().friendlyName || 'TV';
        const liveActive = document.getElementById('live-view')?.classList.contains('active');

        if (liveActive) {
            this.castLiveStream?.();
        } else {
            const overlay = document.getElementById('cast-overlay');
            const deviceLabel = document.getElementById('cast-device-name');
            if (overlay) overlay.style.display = 'flex';
            if (deviceLabel) deviceLabel.textContent = `Casting to ${deviceName}`;

            const videoEl = document.getElementById('game-video');
            if (videoEl) videoEl.pause();

            if (this.activeMatchId && this.activeSlot) {
                const src = `${window.location.origin}/api/matches/${this.activeMatchId}/video/${this.activeSlot}`;
                this.castMedia(src);
            }
        }

        this.updateRemotePlaybackNote();
    },

    onCastDisconnected() {
        this.castSession = null;
        const castBtns = ['cast-btn', 'cast-btn-live']
            .map((id) => document.getElementById(id))
            .filter(Boolean);
        castBtns.forEach((btn) => btn.classList.remove('casting'));

        const overlay = document.getElementById('cast-overlay');
        if (overlay) overlay.style.display = 'none';
        const liveOverlay = document.getElementById('cast-overlay-live');
        if (liveOverlay) liveOverlay.style.display = 'none';

        // If we were casting the live stream and the user is still on the
        // live view with the feed up, resume local playback so the screen
        // doesn't sit blank after the cast session ends.
        this.resumeLiveAfterCast?.();
        this.updateRemotePlaybackNote();
    },

    castMedia(url) {
        if (!this.castSession) return;

        const match = this.matches.find((item) => item.id === this.activeMatchId);
        const videoEl = document.getElementById('game-video');
        const absoluteUrl = url.startsWith('http') ? url : window.location.origin + url;
        const mediaInfo = new chrome.cast.media.MediaInfo(absoluteUrl, 'video/mp4');
        mediaInfo.streamType = chrome.cast.media.StreamType.BUFFERED;
        if (match) {
            const metadata = new chrome.cast.media.GenericMediaMetadata();
            metadata.title = `${match.home_team} vs ${match.away_team}`;
            metadata.subtitle = this.slotLabel(this.activeSlot || 'full');
            if (match.home_logo) {
                metadata.images = [
                    { url: `${window.location.origin}/api/matches/${match.id}/logo/home` },
                ];
            }
            mediaInfo.metadata = metadata;
        }
        const request = new chrome.cast.media.LoadRequest(mediaInfo);
        request.currentTime = videoEl?.currentTime || 0;
        request.autoplay = true;

        this.castSession.loadMedia(request).then(
            () => console.log('Cast media loaded'),
            (err) => console.error('Cast load error', err)
        );
    },

    updateRemotePlaybackNote() {
        const note = document.getElementById('remote-playback-note');
        if (!note) return;

        if (this.castSession) {
            note.textContent = 'Chromecast connected. Playback is being sent to the selected TV.';
            return;
        }

        if (this.airplayActive) {
            note.textContent = 'AirPlay is active. Playback is being sent to the selected Apple TV or AirPlay 2 display.';
            return;
        }

        if (this.airplayAvailable) {
            note.textContent = this.castAvailable
                ? 'Adaptive HLS playback is active when supported. Use AirPlay or Cast to send playback to a TV.'
                : 'Adaptive HLS playback is active when supported. AirPlay is available on supported Safari or WebKit devices.';
            return;
        }

        if (this.castAvailable) {
            note.textContent = 'Adaptive HLS playback is active when supported. Cast is available in Chrome when a Chromecast device is on the same network.';
            return;
        }

        if (this.castSupportedBrowser && !this.castSecureContextAllowed) {
            note.textContent = 'Cast is unavailable because this page is not loaded from HTTPS or localhost.';
            return;
        }

        if (this.castSupportedBrowser && !this.castSdkReady) {
            note.textContent = 'Cast is available in Chrome or Edge when this page is opened over HTTPS or localhost.';
            return;
        }

        note.textContent = 'Adaptive HLS playback is used when available, with direct MP4 fallback for simple playback and casting.';
    },

    // ===== PLAYBACK =====
    getStreamUrls(matchId, slot) {
        return {
            hlsUrl: `/api/matches/${matchId}/hls/${slot}/master.m3u8`,
            mp4Url: `/api/matches/${matchId}/video/${slot}`,
        };
    },

    loadPlaybackSource(videoEl, hlsUrl, mp4Url, playRequestToken) {
        const useMp4Fallback = () => {
            if (playRequestToken !== this._playRequestToken) return;
            this.destroyHlsPlayer();
            if (videoEl._nativeHlsFallbackHandler) {
                videoEl.removeEventListener('error', videoEl._nativeHlsFallbackHandler);
                videoEl._nativeHlsFallbackHandler = null;
            }
            videoEl.onerror = () => this.showNoVideoState();
            videoEl.src = mp4Url;
            videoEl.load();
        };

        if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
            if (videoEl._nativeHlsFallbackHandler) {
                videoEl.removeEventListener('error', videoEl._nativeHlsFallbackHandler);
            }
            videoEl._nativeHlsFallbackHandler = useMp4Fallback;
            videoEl.addEventListener('error', useMp4Fallback, { once: true });
            videoEl.src = hlsUrl;
            videoEl.load();
            return;
        }

        if (window.Hls && window.Hls.isSupported()) {
            const hls = new window.Hls({
                enableWorker: true,
                backBufferLength: 90,
                maxBufferLength: 60,
                maxMaxBufferLength: 120,
            });
            this.hlsPlayer = hls;
            hls.attachMedia(videoEl);
            hls.on(window.Hls.Events.MEDIA_ATTACHED, () => {
                if (playRequestToken !== this._playRequestToken) return;
                hls.loadSource(hlsUrl);
            });
            hls.on(window.Hls.Events.ERROR, (_, data) => {
                if (!data?.fatal) return;
                useMp4Fallback();
            });
            return;
        }

        useMp4Fallback();
    },

    destroyHlsPlayer() {
        if (!this.hlsPlayer) return;
        this.hlsPlayer.destroy();
        this.hlsPlayer = null;
    },

    showProcessingState() {
        this.activeSlot = null;
        this.destroyHlsPlayer();
        this._stopVodHeartbeat();
        const videoEl = document.getElementById('game-video');
        const placeholder = document.getElementById('video-placeholder');

        if (videoEl) {
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
            videoEl.classList.remove('active');
            videoEl.style.display = 'none';
            videoEl.onerror = null;
            videoEl.onloadeddata = null;
        }

        if (placeholder) {
            placeholder.style.display = 'flex';
            const label = placeholder.querySelector('.player-label');
            if (label) label.textContent = 'VIDEO IS BEING PROCESSED';
        }
    },

    showNoVideoState() {
        this.activeSlot = null;
        this.destroyHlsPlayer();
        this._stopVodHeartbeat();
        const videoEl = document.getElementById('game-video');
        const placeholder = document.getElementById('video-placeholder');

        if (videoEl) {
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
            videoEl.classList.remove('active');
            videoEl.style.display = 'none';
            videoEl.onerror = null;
            videoEl.onloadeddata = null;
        }

        if (placeholder) {
            placeholder.style.display = 'flex';
            const label = placeholder.querySelector('.player-label');
            if (label) label.textContent = 'VIDEO NOT AVAILABLE';
        }
    },

    playSlot(matchId, slot) {
        this.activeSlot = slot;
        const match = this.matches.find(m => m.id === matchId);
        if (match && match.slug) {
            const slotSuffix = slot === 'full' ? '' : `/${slot.replace('_', '-')}`;
            const url = `/match/${match.slug}${slotSuffix}`;
            window.history.replaceState(
                { view: 'game', matchId, slug: match.slug, slot },
                '', url,
            );
        }
        const playRequestToken = ++this._playRequestToken;
        const videoEl = document.getElementById('game-video');
        const placeholder = document.getElementById('video-placeholder');
        const { hlsUrl, mp4Url } = this.getStreamUrls(matchId, slot);

        this.destroyHlsPlayer();
        this._stopPositionTracking();
        this._stopVodHeartbeat();

        // Kick the heartbeat off as soon as we know match + slot — don't
        // wait for the video to fully load. Caddy may serve the very first
        // segment before `loadeddata` fires, and we want the registry to
        // see this viewer immediately so the admin UI shows the count.
        this._startVodHeartbeat(matchId, slot, videoEl);

        document.querySelectorAll('.segment-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.slot === slot);
        });

        // Apply saved speed preference
        const savedSpeed = this._getSavedSpeed();
        if (savedSpeed) videoEl.playbackRate = savedSpeed;

        videoEl.preload = 'auto';
        videoEl.onerror = null;
        videoEl.onloadeddata = () => {
            if (playRequestToken !== this._playRequestToken) return;
            placeholder.style.display = 'none';
            videoEl.style.display = 'block';
            videoEl.classList.add('active');

            // Resume from saved position
            const savedPos = this._getSavedPosition(matchId, slot);
            if (savedPos && videoEl.duration &&
                savedPos > POSITION_RESUME_THRESHOLD &&
                savedPos < videoEl.duration - POSITION_END_MARGIN) {
                videoEl.currentTime = savedPos;
            }

            // Start tracking position
            this._startPositionTracking(matchId, slot);
        };

        // Track speed changes
        videoEl.onratechange = () => {
            this._saveSpeed(videoEl.playbackRate);
        };

        this.loadPlaybackSource(videoEl, hlsUrl, mp4Url, playRequestToken);

        if (this.castSession) {
            this.castMedia(mp4Url);
        }

        this.updateRemotePlaybackNote();
    },

    // ===== PLAYBACK POSITION MEMORY =====
    _getSavedPositions() {
        try {
            return JSON.parse(localStorage.getItem(POSITION_STORAGE_KEY) || '{}');
        } catch { return {}; }
    },

    _getSavedPosition(matchId, slot) {
        const positions = this._getSavedPositions();
        return positions[`${matchId}/${slot}`] || null;
    },

    _savePosition(matchId, slot, time) {
        const positions = this._getSavedPositions();
        positions[`${matchId}/${slot}`] = Math.floor(time);
        // Keep only the most recent 50 entries
        const keys = Object.keys(positions);
        if (keys.length > 50) {
            delete positions[keys[0]];
        }
        try {
            localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify(positions));
        } catch { /* storage full */ }
    },

    _clearSavedPosition(matchId, slot) {
        const positions = this._getSavedPositions();
        delete positions[`${matchId}/${slot}`];
        try {
            localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify(positions));
        } catch { /* ignore */ }
    },

    _startPositionTracking(matchId, slot) {
        this._stopPositionTracking();
        const videoEl = document.getElementById('game-video');
        if (!videoEl) return;

        this._positionInterval = setInterval(() => {
            if (!videoEl.paused && videoEl.currentTime > 0) {
                this._savePosition(matchId, slot, videoEl.currentTime);
            }
        }, POSITION_SAVE_INTERVAL * 1000);

        // Clear position when video ends
        this._onVideoEnded = () => {
            this._clearSavedPosition(matchId, slot);
        };
        videoEl.addEventListener('ended', this._onVideoEnded);
    },

    _stopPositionTracking() {
        if (this._positionInterval) {
            clearInterval(this._positionInterval);
            this._positionInterval = null;
        }
        const videoEl = document.getElementById('game-video');
        if (videoEl && this._onVideoEnded) {
            videoEl.removeEventListener('ended', this._onVideoEnded);
            this._onVideoEnded = null;
        }
    },

    _startVodHeartbeat(matchId, slot, videoEl) {
        this._stopVodHeartbeat();
        if (!matchId || !slot) return;
        const intervalSec = 10; // < HLS_IDLE_SECONDS (15) on the backend
        const url = `/api/matches/${encodeURIComponent(matchId)}/heartbeat?slot=${encodeURIComponent(slot)}`;

        const ping = async ({ skipPausedCheck = false } = {}) => {
            // Skip subsequent pings while paused/ended; admin shouldn't see
            // a "viewer" that's not actually consuming video. The first ping
            // (skipPausedCheck = true) always fires so the registry sees the
            // viewer the moment the page loads, before play has been pressed.
            if (!skipPausedCheck && videoEl && (videoEl.paused || videoEl.ended)) return;
            try {
                const resp = await fetch(url, { method: 'POST', credentials: 'same-origin' });
                if (resp.status === 403) {
                    // Admin killed this stream — stop playback and surface a
                    // toast (UI parity with the live block path).
                    if (videoEl) videoEl.pause();
                    this.showError?.('This stream was disconnected by an administrator.');
                    this._stopVodHeartbeat();
                }
            } catch {
                // Transient network error — try again next tick.
            }
        };
        // Fire one immediately so the registry sees us right when the user
        // navigates to the match, not 10 s later. Subsequent pings only run
        // while playback is active.
        ping({ skipPausedCheck: true });
        this._vodHeartbeatInterval = setInterval(() => ping(), intervalSec * 1000);
    },

    _stopVodHeartbeat() {
        if (this._vodHeartbeatInterval) {
            clearInterval(this._vodHeartbeatInterval);
            this._vodHeartbeatInterval = null;
        }
    },

    // ===== SPEED PREFERENCE =====
    _getSavedSpeed() {
        try {
            const speed = parseFloat(localStorage.getItem(SPEED_STORAGE_KEY));
            return (speed && speed > 0 && speed <= 4) ? speed : null;
        } catch { return null; }
    },

    _saveSpeed(rate) {
        try {
            localStorage.setItem(SPEED_STORAGE_KEY, String(rate));
        } catch { /* ignore */ }
    },

    // ===== KEYBOARD SHORTCUTS =====
    initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Only when game view is active
            if (!this.activeMatchId) return;
            // Don't intercept when typing in inputs
            const tag = (e.target.tagName || '').toLowerCase();
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

            const videoEl = document.getElementById('game-video');
            if (!videoEl || videoEl.style.display === 'none') return;

            switch (e.key) {
                case ' ':
                case 'k':
                    e.preventDefault();
                    videoEl.paused ? videoEl.play() : videoEl.pause();
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    videoEl.currentTime = Math.max(0, videoEl.currentTime - (e.shiftKey ? 30 : 10));
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    videoEl.currentTime = Math.min(videoEl.duration || 0, videoEl.currentTime + (e.shiftKey ? 30 : 10));
                    break;
                case 'j':
                    e.preventDefault();
                    videoEl.currentTime = Math.max(0, videoEl.currentTime - 10);
                    break;
                case 'l':
                    e.preventDefault();
                    videoEl.currentTime = Math.min(videoEl.duration || 0, videoEl.currentTime + 10);
                    break;
                case 'f':
                    e.preventDefault();
                    if (document.fullscreenElement) {
                        document.exitFullscreen();
                    } else {
                        videoEl.requestFullscreen?.();
                    }
                    break;
                case 'm':
                    e.preventDefault();
                    videoEl.muted = !videoEl.muted;
                    break;
                case ',':
                    if (e.shiftKey) { // <
                        e.preventDefault();
                        videoEl.playbackRate = Math.max(0.25, videoEl.playbackRate - 0.25);
                    }
                    break;
                case '.':
                    if (e.shiftKey) { // >
                        e.preventDefault();
                        videoEl.playbackRate = Math.min(4, videoEl.playbackRate + 0.25);
                    }
                    break;
                case '0':
                case 'Home':
                    e.preventDefault();
                    videoEl.currentTime = 0;
                    break;
                case 'End':
                    e.preventDefault();
                    videoEl.currentTime = videoEl.duration || 0;
                    break;
            }
        });
    },

    // ===== NEXT/PREVIOUS MATCH =====
    getAdjacentMatch(direction) {
        if (!this.activeMatchId) return null;
        const sorted = [...this.matches].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
        const idx = sorted.findIndex(m => m.id === this.activeMatchId);
        if (idx < 0) return null;
        const targetIdx = idx + direction;
        return (targetIdx >= 0 && targetIdx < sorted.length) ? sorted[targetIdx] : null;
    },

    goToNextMatch() {
        const match = this.getAdjacentMatch(1);
        if (match) this.openMatch(match.id);
    },

    goToPreviousMatch() {
        const match = this.getAdjacentMatch(-1);
        if (match) this.openMatch(match.id);
    },
};
