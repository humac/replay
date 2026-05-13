// Semantic metadata for `player_user_links.relationship` values.
// One source of truth for Coach > Roster, Player Development, and the
// Admin > Users 360 drawer. Backend enum is closed:
// `self | parent | guardian | family` (models.py `_VALID_PLAYER_RELATIONSHIPS`).

const RELATIONSHIP_META = {
    self: {
        label: 'Self',
        tone: 'self',
        tooltip: 'The player themselves',
        iconPath: 'M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z',
    },
    parent: {
        label: 'Parent',
        tone: 'parent',
        tooltip: 'A parent of the player',
        iconPath: 'M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-.18 0-.36.03-.53.05.62.83.99 1.84.99 2.95s-.37 2.12-.99 2.95c.17.02.35.05.53.05zm-4 0c1.66 0 2.99-1.34 2.99-3S13.66 5 12 5 9 6.34 9 8s1.34 3 3 3zm0 2c-2 0-6 1-6 3v3h12v-3c0-2-4-3-6-3zm5.31.49C18.34 14.18 19 15.04 19 16v3h3v-3c0-1.43-2.5-2.31-4.69-2.51zM8 11c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm-.31 2.49C5.5 13.69 3 14.57 3 16v3h3v-3c0-.96.66-1.82 1.69-2.51z',
    },
    guardian: {
        label: 'Guardian',
        tone: 'guardian',
        tooltip: 'Legal or registered guardian — can manage the player account',
        iconPath: 'M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z',
    },
    family: {
        label: 'Family',
        tone: 'family',
        tooltip: 'Family member of the player',
        iconPath: 'M9 12c1.66 0 3-1.34 3-3S10.66 6 9 6 6 7.34 6 9s1.34 3 3 3zm0 2c-2.21 0-6 1.1-6 3.3V20h12v-2.7C15 15.1 11.21 14 9 14zm9-2v-2h-2V8h-2v2h-2v2h2v2h2v-2h2z',
    },
};

const RELATIONSHIP_DEFAULT_TONE = 'family';

export const relationshipMetaMixin = {
    /** Look up label/tooltip/icon-path/tone for a relationship enum value. */
    relationshipMeta(value) {
        const key = String(value || '').trim().toLowerCase();
        return RELATIONSHIP_META[key] || {
            label: key ? key.replace(/_/g, ' ') : 'Link',
            tone: RELATIONSHIP_DEFAULT_TONE,
            tooltip: '',
            iconPath: RELATIONSHIP_META.family.iconPath,
        };
    },

    /**
     * Render a semantic relationship pill (icon + label + colored tone).
     * Returns an HTML string. Caller chooses whether to wrap in a button,
     * link, or plain span by passing `{ as }` — defaults to <span>.
     */
    relationshipPillHtml(value, { extraClass = '', as = 'span', titleSuffix = '' } = {}) {
        const meta = this.relationshipMeta(value);
        const tag = (as === 'button') ? 'button' : 'span';
        const title = titleSuffix ? `${meta.tooltip} — ${titleSuffix}` : meta.tooltip;
        const safeTitle = this.esc(title || '');
        const cls = `relationship-pill${extraClass ? ' ' + extraClass : ''}`;
        const icon = `<svg class="relationship-pill-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${meta.iconPath}"></path></svg>`;
        return `<${tag} class="${cls}" data-tone="${this.esc(meta.tone)}" title="${safeTitle}">${icon}<span class="relationship-pill-label">${this.esc(meta.label)}</span></${tag}>`;
    },
};
