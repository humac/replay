// Playback, AirPlay, and Chromecast methods.

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

        const castBtn = document.getElementById('cast-btn');
        if (!isAvailable || !window.cast?.framework || !window.chrome?.cast) {
            if (castBtn && this.castSupportedBrowser) {
                castBtn.style.display = 'flex';
                castBtn.classList.add('remote-playback-btn-disabled');
            }
            this.updateRemotePlaybackNote();
            return;
        }

        if (castBtn) {
            castBtn.style.display = 'flex';
            castBtn.classList.remove('remote-playback-btn-disabled');
        }

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
        const castBtn = document.getElementById('cast-btn');
        if (castBtn) castBtn.classList.add('casting');

        const overlay = document.getElementById('cast-overlay');
        const deviceName = document.getElementById('cast-device-name');
        if (overlay) overlay.style.display = 'flex';
        if (deviceName) {
            const name = this.castSession.getCastDevice().friendlyName || 'TV';
            deviceName.textContent = `Casting to ${name}`;
        }

        const videoEl = document.getElementById('game-video');
        if (videoEl) videoEl.pause();

        if (this.activeMatchId && this.activeSlot) {
            const src = `${window.location.origin}/api/matches/${this.activeMatchId}/video/${this.activeSlot}`;
            this.castMedia(src);
        }

        this.updateRemotePlaybackNote();
    },

    onCastDisconnected() {
        this.castSession = null;
        const castBtn = document.getElementById('cast-btn');
        if (castBtn) castBtn.classList.remove('casting');

        const overlay = document.getElementById('cast-overlay');
        if (overlay) overlay.style.display = 'none';
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

        document.querySelectorAll('.segment-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.slot === slot);
        });

        videoEl.preload = 'auto';
        videoEl.onerror = null;
        videoEl.onloadeddata = () => {
            if (playRequestToken !== this._playRequestToken) return;
            placeholder.style.display = 'none';
            videoEl.style.display = 'block';
            videoEl.classList.add('active');
        };
        this.loadPlaybackSource(videoEl, hlsUrl, mp4Url, playRequestToken);

        if (this.castSession) {
            this.castMedia(mp4Url);
        }

        this.updateRemotePlaybackNote();
    },
};
