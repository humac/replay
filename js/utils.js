// Pure utility functions — no state dependencies.
// All methods receive `this` from the merged app object at runtime.

export const utilsMixin = {
    esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    },

    formatDate(dateStr) {
        if (!dateStr) return '-';
        try {
            const d = new Date(dateStr + 'T00:00:00');
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
        } catch {
            return dateStr;
        }
    },

    formatBytes(bytes) {
        const value = Number(bytes || 0);
        if (value < 1024) return `${value} B`;
        const units = ['KB', 'MB', 'GB', 'TB'];
        let size = value;
        let unitIndex = -1;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex += 1;
        }
        return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
    },

    formatDuration(seconds) {
        const total = Number(seconds || 0);
        if (total >= 3600) return `${Math.round(total / 3600)}h`;
        if (total >= 60) return `${Math.round(total / 60)}m`;
        return `${Math.round(total)}s`;
    },

    formatAge(seconds) {
        const total = Number(seconds || 0);
        if (total >= 3600) return `${Math.round(total / 3600)}h ago`;
        if (total >= 60) return `${Math.round(total / 60)}m ago`;
        return `${Math.round(total)}s ago`;
    },

    slotLabel(slot) {
        if (slot === 'first_half') return '1st Half';
        if (slot === 'second_half') return '2nd Half';
        return 'Full Match';
    },

    statusLabel(status) {
        if (status === 'ready') return 'Ready';
        if (status === 'transcoding') return 'Processing';
        if (status === 'completed') return 'Completed';
        if (status === 'cancelled') return 'Cancelled';
        if (status === 'replaced') return 'Replaced';
        return 'Waiting';
    },

    statusClass(status) {
        if (status === 'ready' || status === 'completed') return 'ready';
        if (status === 'transcoding') return 'processing';
        if (status === 'cancelled' || status === 'error' || status === 'replaced') return 'danger';
        return 'neutral';
    },

    slotStatus(m, slot) {
        const vs = m.video_status || {};
        if (vs[slot]) return vs[slot];
        if (m.videos?.[slot]) return 'ready';
        return 'none';
    },

    readySlotsCount(match) {
        const slots = match.format === 'two_halves' ? ['first_half', 'second_half'] : ['full'];
        return slots.filter((slot) => this.slotStatus(match, slot) === 'ready').length;
    },

    matchTranscoding(m) {
        const vs = m.video_status || {};
        return Object.values(vs).some(s => s === 'transcoding');
    },

    anyTranscoding() {
        return this.matches.some(m => {
            const vs = m.video_status || {};
            return Object.values(vs).some(s => s === 'transcoding');
        });
    },

    matchProgressLabel(match) {
        const vs = match.video_status || {};
        const transcodingSlots = Object.entries(vs).filter(([, s]) => s === 'transcoding');
        if (!transcodingSlots.length) return 'PROCESSING';
        const pcts = transcodingSlots.map(([slot]) => {
            const p = this.getSlotProgress(match.id, slot);
            return p ? p.pct : null;
        });
        const known = pcts.filter(p => p !== null);
        if (!known.length) return 'PROCESSING';
        const avg = Math.round(known.reduce((a, b) => a + b, 0) / known.length);
        return `PROCESSING ${avg}%`;
    },

    slotProgressLabel(matchId, slot) {
        const p = this.getSlotProgress(matchId, slot);
        if (!p) return null;
        const stage = p.stage || 'transcoding';
        return `${stage} ${p.pct}%`;
    },
};
