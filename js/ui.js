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

// ----- Custom modal dialog -----
//
// Promise-based replacement for native confirm() / prompt() / alert() so the
// site keeps its dark-broadcast look when destructive operations are
// requested. The DOM is created on demand and torn down on close.

let _activeModal = null;

function escapeHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function openAppModal({
    kind = 'confirm',
    title = '',
    message = '',
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    danger = false,
    options = null,             // [{ value, label }] for prompt-style picker
    initialValue = '',
} = {}) {
    return new Promise((resolve) => {
        if (_activeModal) _activeModal.close(null);

        const wrap = document.createElement('div');
        wrap.className = 'app-modal';
        wrap.setAttribute('role', 'dialog');
        wrap.setAttribute('aria-modal', 'true');

        const backdrop = document.createElement('div');
        backdrop.className = 'app-modal-backdrop';

        const card = document.createElement('div');
        card.className = `app-modal-card${danger ? ' is-danger' : ''}`;
        card.innerHTML = `
            <span class="app-modal-kicker">${danger ? 'Confirm action' : (kind === 'alert' ? 'Status' : 'Confirm')}</span>
            <h3 class="app-modal-title">${escapeHtml(title)}</h3>
            <p class="app-modal-message">${escapeHtml(message)}</p>
        `;

        let pickerEl = null;
        if (kind === 'prompt' && Array.isArray(options) && options.length) {
            pickerEl = document.createElement('div');
            pickerEl.className = 'app-modal-picker';
            options.forEach((opt) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'app-modal-picker-btn';
                btn.dataset.value = opt.value;
                btn.textContent = opt.label;
                if (opt.value === initialValue) btn.classList.add('is-active');
                btn.addEventListener('click', () => {
                    pickerEl.querySelectorAll('.app-modal-picker-btn').forEach((b) => b.classList.remove('is-active'));
                    btn.classList.add('is-active');
                });
                pickerEl.appendChild(btn);
            });
            card.appendChild(pickerEl);
        }

        const actions = document.createElement('div');
        actions.className = 'app-modal-actions';
        actions.innerHTML = kind === 'alert'
            ? `<button type="button" class="btn-primary app-modal-confirm">${escapeHtml(confirmLabel || 'Close')}</button>`
            : `
                <button type="button" class="btn-secondary app-modal-cancel">${escapeHtml(cancelLabel)}</button>
                <button type="button" class="${danger ? 'btn-danger' : 'btn-primary'} app-modal-confirm">${escapeHtml(confirmLabel)}</button>
            `;
        card.appendChild(actions);

        wrap.appendChild(backdrop);
        wrap.appendChild(card);
        document.body.appendChild(wrap);
        requestAnimationFrame(() => wrap.classList.add('is-open'));

        const previousFocus = document.activeElement;
        const confirmBtn = card.querySelector('.app-modal-confirm');
        const cancelBtn = card.querySelector('.app-modal-cancel');

        const close = (value) => {
            if (!wrap.isConnected) return;
            wrap.classList.remove('is-open');
            wrap.classList.add('is-closing');
            setTimeout(() => wrap.remove(), 200);
            document.removeEventListener('keydown', onKey);
            _activeModal = null;
            try { previousFocus?.focus?.(); } catch { /* ignore */ }
            resolve(value);
        };

        const onConfirm = () => {
            if (kind === 'prompt') {
                const active = pickerEl?.querySelector('.app-modal-picker-btn.is-active');
                close(active ? active.dataset.value : initialValue);
            } else if (kind === 'alert') {
                close(true);
            } else {
                close(true);
            }
        };
        const onCancel = () => close(kind === 'prompt' ? null : false);
        const onKey = (e) => {
            if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
            if (e.key === 'Enter' && document.activeElement?.tagName !== 'BUTTON') {
                e.preventDefault(); onConfirm();
            }
        };

        confirmBtn.addEventListener('click', onConfirm);
        cancelBtn?.addEventListener('click', onCancel);
        backdrop.addEventListener('click', onCancel);
        document.addEventListener('keydown', onKey);

        _activeModal = { close };
        // Focus handling — confirm by default, cancel for destructive prompts.
        setTimeout(() => (danger ? cancelBtn || confirmBtn : confirmBtn).focus(), 0);
    });
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

    /** Promise<boolean> — resolves true when the user confirms, false on cancel/escape. */
    confirmAction({ title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false } = {}) {
        return openAppModal({ kind: 'confirm', title, message, confirmLabel, cancelLabel, danger });
    },

    /** Promise<string|null> — resolves the chosen option value, or null on cancel. */
    promptChoice({ title, message, options, initialValue = '', confirmLabel = 'Continue', cancelLabel = 'Cancel' } = {}) {
        return openAppModal({ kind: 'prompt', title, message, options, initialValue, confirmLabel, cancelLabel });
    },

    /** Promise<true> — informational modal with a single dismiss button. */
    notifyModal({ title, message, confirmLabel = 'Close' } = {}) {
        return openAppModal({ kind: 'alert', title, message, confirmLabel });
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
