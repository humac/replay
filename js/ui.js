// Centralized UI feedback: toast notifications and button loading states.

let _toastContainer = null;

function getToastContainer() {
    if (_toastContainer && _toastContainer.isConnected) return _toastContainer;
    _toastContainer = document.createElement('div');
    _toastContainer.className = 'toast-container';
    _toastContainer.setAttribute('aria-live', 'polite');
    document.body.appendChild(_toastContainer);
    return _toastContainer;
}

function showToast(message, { type = 'info', duration = 4000 } = {}) {
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('role', 'status');

    const icons = {
        success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
        error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };

    const iconHtml = icons[type] || icons.info;
    const textEl = document.createElement('span');
    textEl.className = 'toast-text';
    textEl.textContent = message;

    toast.innerHTML = iconHtml;
    toast.appendChild(textEl);

    const dismiss = document.createElement('button');
    dismiss.className = 'toast-dismiss';
    dismiss.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    dismiss.onclick = () => removeToast(toast);
    toast.appendChild(dismiss);

    container.appendChild(toast);
    // Trigger entrance animation
    requestAnimationFrame(() => toast.classList.add('toast-visible'));

    if (duration > 0) {
        setTimeout(() => removeToast(toast), duration);
    }

    return toast;
}

function removeToast(toast) {
    if (!toast || !toast.isConnected) return;
    toast.classList.remove('toast-visible');
    toast.classList.add('toast-exit');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
    // Fallback if transitionend doesn't fire
    setTimeout(() => { if (toast.isConnected) toast.remove(); }, 400);
}

export const uiMixin = {
    showSuccess(message) {
        showToast(message, { type: 'success' });
    },

    showError(message) {
        showToast(message, { type: 'error', duration: 6000 });
    },

    showInfo(message) {
        showToast(message, { type: 'info' });
    },

    /** Set a button into a loading state; returns a restore function. */
    btnLoading(btn, loadingText) {
        if (!btn) return () => {};
        const original = btn.textContent;
        const wasDisabled = btn.disabled;
        btn.disabled = true;
        btn.textContent = loadingText;
        btn.classList.add('btn-loading');
        return (restoreText) => {
            btn.disabled = wasDisabled;
            btn.textContent = restoreText || original;
            btn.classList.remove('btn-loading');
        };
    },
};
