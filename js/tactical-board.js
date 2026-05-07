// Tactical board (Phase 6c) — SVG-based soccer pitch editor + read-only renderer.
//
// The board is a structured scene stored on coaching_notes.tactical_board_json
// (see models.py validate_tactical_board_payload). MVP only ships
// `pitch_kind: "soccer_full"` but the dispatch goes through PITCH_RENDERERS
// so a future sport adds an entry without touching call sites.
//
// Coordinates are normalized 0..1 across pitch length (x) and width (y).
// Conversion to SVG happens here at render time.
//
// The editor is mounted INLINE into the observation composer (not as a
// nested modal) because openAppModal supports only one modal at a time
// — opening a nested modal would close the parent observation composer
// and lose every coach-typed field.

const PITCH_VIEWBOX = { w: 1050, h: 680 };
const SOCCER_LINE = '#f8fafc';
const SOCCER_GRASS = '#1e9d4a';
const SOCCER_GRASS_DARK = '#168a3f';

function nextId(prefix) {
    return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function clamp01(v) {
    if (typeof v !== 'number' || !isFinite(v)) return 0;
    if (v < 0) return 0;
    if (v > 1) return 1;
    return v;
}

function escAttr(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/** Local in-section confirmation. Renders into a host <div> already
 *  present in the section markup; resolves true on Confirm, false on
 *  Cancel. Does NOT use openAppModal — the tactical-board section is
 *  always mounted inside the observation composer's formModal, and
 *  openAppModal would close the parent modal, losing every coach-
 *  typed field. The host element is hidden when the promise settles
 *  so the section returns to its normal layout. */
function runLocalConfirm(host, { message, confirmLabel = 'Confirm', cancelLabel = 'Cancel' }) {
    return new Promise((resolve) => {
        if (!host) { resolve(false); return; }
        host.hidden = false;
        host.innerHTML = `
            <p class="tb-confirm-bar-msg">${escAttr(message || 'Are you sure?')}</p>
            <div class="tb-confirm-bar-actions">
                <button type="button" class="tb-section-btn" data-tb-confirm-cancel>${escAttr(cancelLabel)}</button>
                <button type="button" class="tb-section-btn tb-section-btn--danger" data-tb-confirm-ok>${escAttr(confirmLabel)}</button>
            </div>
        `;
        const close = (value) => {
            host.hidden = true;
            host.innerHTML = '';
            resolve(value);
        };
        host.querySelector('[data-tb-confirm-cancel]').addEventListener('click', (e) => { e.preventDefault(); close(false); });
        host.querySelector('[data-tb-confirm-ok]').addEventListener('click', (e) => { e.preventDefault(); close(true); });
        // Focus the destructive button only after a tick so the
        // alertdialog announcement fires before the focus shift.
        setTimeout(() => host.querySelector('[data-tb-confirm-ok]')?.focus(), 0);
    });
}

/** Defensive read — accept anything the Phase 6a loose JSON column may
 * have stored. Returns either a normalized scene or null. Never throws. */
export function normalizeBoardForRender(board) {
    if (!board || typeof board !== 'object') return null;
    const pitch = board.pitch_kind || 'soccer_full';
    if (pitch !== 'soccer_full') return null;
    const tokens = Array.isArray(board.tokens) ? board.tokens : [];
    const shapes = Array.isArray(board.shapes) ? board.shapes : [];
    const validKinds = new Set(['player', 'ball']);
    const validShapeKinds = new Set(['arrow', 'line', 'zone', 'label']);
    const cleanTokens = tokens
        .filter((t) => t && typeof t === 'object' && validKinds.has(t.kind))
        .map((t) => ({
            id: typeof t.id === 'string' ? t.id : nextId('token'),
            kind: t.kind,
            x: clamp01(t.x),
            y: clamp01(t.y),
            label: typeof t.label === 'string' ? t.label.slice(0, 24) : '',
            player_id: typeof t.player_id === 'string' || typeof t.player_id === 'number' ? String(t.player_id) : '',
        }));
    const cleanShapes = shapes
        .filter((s) => s && typeof s === 'object' && validShapeKinds.has(s.kind))
        .map((s) => {
            const base = { id: typeof s.id === 'string' ? s.id : nextId('shape'), kind: s.kind };
            if (s.kind === 'arrow' || s.kind === 'line') {
                return { ...base, x1: clamp01(s.x1), y1: clamp01(s.y1), x2: clamp01(s.x2), y2: clamp01(s.y2) };
            }
            if (s.kind === 'zone') {
                let w = clamp01(s.w), h = clamp01(s.h);
                if (w <= 0) w = 0.1; if (h <= 0) h = 0.1;
                const x = clamp01(s.x), y = clamp01(s.y);
                return { ...base, x, y, w: Math.min(w, 1 - x), h: Math.min(h, 1 - y) };
            }
            return { ...base, x: clamp01(s.x), y: clamp01(s.y), text: typeof s.text === 'string' ? s.text.slice(0, 80) : '' };
        });
    // MVP only ships landscape soccer pitches; the backend
    // _VALID_BOARD_ORIENTATIONS gates anything else. When a future
    // sport adds a new orientation, branch on it here AND add a
    // matching renderer to PITCH_RENDERERS.
    return {
        version: 1,
        pitch_kind: 'soccer_full',
        orientation: 'landscape',
        tokens: cleanTokens,
        shapes: cleanShapes,
    };
}

/** True if a board has anything renderable. */
export function boardHasContent(board) {
    const n = normalizeBoardForRender(board);
    if (!n) return false;
    return n.tokens.length > 0 || n.shapes.length > 0;
}

function renderSoccerPitchSvgMarkings() {
    const W = PITCH_VIEWBOX.w, H = PITCH_VIEWBOX.h;
    const margin = 30;
    const halfX = W / 2;
    const halfY = H / 2;
    const goalAreaW = 60, goalAreaH = 220;
    const penaltyAreaW = 140, penaltyAreaH = 380;
    const centerR = 80;
    const penaltySpotOffset = 100;
    const goalDepth = 15, goalWidth = 110;
    return `
        <rect x="0" y="0" width="${W}" height="${H}" fill="url(#tb-grass-grad)"/>
        <g stroke="${SOCCER_LINE}" stroke-width="3" fill="none" stroke-linejoin="miter">
            <rect x="${margin}" y="${margin}" width="${W - margin * 2}" height="${H - margin * 2}"/>
            <line x1="${halfX}" y1="${margin}" x2="${halfX}" y2="${H - margin}"/>
            <circle cx="${halfX}" cy="${halfY}" r="${centerR}"/>
            <circle cx="${halfX}" cy="${halfY}" r="3" fill="${SOCCER_LINE}"/>
            <rect x="${margin}" y="${halfY - penaltyAreaH / 2}" width="${penaltyAreaW}" height="${penaltyAreaH}"/>
            <rect x="${margin}" y="${halfY - goalAreaH / 2}" width="${goalAreaW}" height="${goalAreaH}"/>
            <circle cx="${margin + penaltySpotOffset}" cy="${halfY}" r="3" fill="${SOCCER_LINE}"/>
            <path d="M ${margin + penaltyAreaW} ${halfY - 50} A 60 60 0 0 1 ${margin + penaltyAreaW} ${halfY + 50}"/>
            <rect x="${margin - goalDepth}" y="${halfY - goalWidth / 2}" width="${goalDepth}" height="${goalWidth}" fill="rgba(255,255,255,0.15)"/>
            <rect x="${W - margin - penaltyAreaW}" y="${halfY - penaltyAreaH / 2}" width="${penaltyAreaW}" height="${penaltyAreaH}"/>
            <rect x="${W - margin - goalAreaW}" y="${halfY - goalAreaH / 2}" width="${goalAreaW}" height="${goalAreaH}"/>
            <circle cx="${W - margin - penaltySpotOffset}" cy="${halfY}" r="3" fill="${SOCCER_LINE}"/>
            <path d="M ${W - margin - penaltyAreaW} ${halfY - 50} A 60 60 0 0 0 ${W - margin - penaltyAreaW} ${halfY + 50}"/>
            <rect x="${W - margin}" y="${halfY - goalWidth / 2}" width="${goalDepth}" height="${goalWidth}" fill="rgba(255,255,255,0.15)"/>
            <path d="M ${margin} ${margin + 12} A 12 12 0 0 1 ${margin + 12} ${margin}"/>
            <path d="M ${W - margin - 12} ${margin} A 12 12 0 0 1 ${W - margin} ${margin + 12}"/>
            <path d="M ${margin} ${H - margin - 12} A 12 12 0 0 0 ${margin + 12} ${H - margin}"/>
            <path d="M ${W - margin} ${H - margin - 12} A 12 12 0 0 0 ${W - margin - 12} ${H - margin}"/>
        </g>
    `;
}

const PITCH_RENDERERS = {
    soccer_full: renderSoccerPitchSvgMarkings,
};

function renderShapeSvg(shape, opts = {}) {
    const W = PITCH_VIEWBOX.w, H = PITCH_VIEWBOX.h;
    const sel = opts.selectedId === shape.id;
    const stroke = sel ? '#fbbf24' : '#fde047';
    const strokeAttr = sel ? '4.5' : '3';
    const dataAttr = opts.editor
        ? `data-shape-id="${escAttr(shape.id)}" class="tb-shape${sel ? ' is-selected' : ''}"`
        : `class="tb-shape"`;
    if (shape.kind === 'arrow' || shape.kind === 'line') {
        const x1 = shape.x1 * W, y1 = shape.y1 * H, x2 = shape.x2 * W, y2 = shape.y2 * H;
        const marker = shape.kind === 'arrow' ? ' marker-end="url(#tb-arrow)"' : '';
        return `<line ${dataAttr} x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${strokeAttr}" stroke-linecap="round"${marker}/>`;
    }
    if (shape.kind === 'zone') {
        const x = shape.x * W, y = shape.y * H, w = shape.w * W, h = shape.h * H;
        return `<rect ${dataAttr} x="${x}" y="${y}" width="${w}" height="${h}" fill="rgba(253, 224, 71, 0.18)" stroke="${stroke}" stroke-width="${strokeAttr}" stroke-dasharray="8 6" rx="4"/>`;
    }
    if (shape.kind === 'label') {
        const x = shape.x * W, y = shape.y * H;
        const text = escAttr(shape.text || '');
        const approxW = Math.min(420, Math.max(60, (shape.text || '').length * 14 + 24));
        return `<g ${dataAttr}>
            <rect x="${x - approxW / 2}" y="${y - 22}" width="${approxW}" height="44" rx="22" fill="rgba(15, 23, 42, 0.78)" stroke="${stroke}" stroke-width="${strokeAttr}"/>
            <text x="${x}" y="${y + 7}" text-anchor="middle" fill="#fde047" font-size="22" font-weight="700" font-family="system-ui,-apple-system,sans-serif">${text}</text>
        </g>`;
    }
    return '';
}

function renderTokenSvg(token, opts = {}) {
    const W = PITCH_VIEWBOX.w, H = PITCH_VIEWBOX.h;
    const x = token.x * W, y = token.y * H;
    const sel = opts.selectedId === token.id;
    const dataAttr = opts.editor
        ? `data-token-id="${escAttr(token.id)}" class="tb-token${sel ? ' is-selected' : ''}"`
        : `class="tb-token"`;
    if (token.kind === 'ball') {
        return `<g ${dataAttr}>
            <circle cx="${x}" cy="${y}" r="${sel ? 18 : 15}" fill="#f8fafc" stroke="#0f172a" stroke-width="${sel ? 4 : 2}"/>
            <circle cx="${x}" cy="${y}" r="6" fill="#0f172a"/>
        </g>`;
    }
    const r = sel ? 26 : 22;
    const stroke = sel ? '#fbbf24' : '#0f172a';
    const fill = '#1771c9';
    const label = escAttr(token.label || '');
    return `<g ${dataAttr}>
        <circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sel ? 4 : 3}"/>
        ${label ? `<text x="${x}" y="${y + 7}" text-anchor="middle" fill="#ffffff" font-size="22" font-weight="700" font-family="system-ui,-apple-system,sans-serif">${label}</text>` : ''}
    </g>`;
}

function renderDefs() {
    return `<defs>
        <linearGradient id="tb-grass-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="${SOCCER_GRASS}"/>
            <stop offset="1" stop-color="${SOCCER_GRASS_DARK}"/>
        </linearGradient>
        <marker id="tb-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#fde047"/>
        </marker>
    </defs>`;
}

/** Public — render a board as an SVG string. opts.editor adds per-item
 * data attributes used by the editor click/drag handlers. opts.size
 * controls the wrapper class for sizing (preview / chip / full). */
export function renderTacticalBoardSvg(board, opts = {}) {
    const normalized = normalizeBoardForRender(board);
    if (!normalized) {
        return `<div class="tb-empty" role="img" aria-label="Tactical board (empty)">No tactical board</div>`;
    }
    const renderer = PITCH_RENDERERS[normalized.pitch_kind];
    if (!renderer) {
        return `<div class="tb-empty" role="img" aria-label="Tactical board (unsupported)">Unsupported pitch (${escAttr(normalized.pitch_kind)})</div>`;
    }
    const sizeClass = opts.size ? ` tb-svg-wrap--${opts.size}` : '';
    const editorClass = opts.editor ? ' tb-svg-wrap--editor' : '';
    const summaryParts = [];
    if (normalized.tokens.length) summaryParts.push(`${normalized.tokens.length} token${normalized.tokens.length === 1 ? '' : 's'}`);
    if (normalized.shapes.length) summaryParts.push(`${normalized.shapes.length} shape${normalized.shapes.length === 1 ? '' : 's'}`);
    const summary = summaryParts.length ? `Tactical board — ${summaryParts.join(', ')}` : 'Tactical board (empty)';
    return `<div class="tb-svg-wrap${sizeClass}${editorClass}" role="img" aria-label="${escAttr(summary)}">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${PITCH_VIEWBOX.w} ${PITCH_VIEWBOX.h}" preserveAspectRatio="xMidYMid meet" class="tb-svg">
            ${renderDefs()}
            ${renderer()}
            <g class="tb-shapes">${normalized.shapes.map((s) => renderShapeSvg(s, opts)).join('')}</g>
            <g class="tb-tokens">${normalized.tokens.map((t) => renderTokenSvg(t, opts)).join('')}</g>
        </svg>
    </div>`;
}

/** Build the tactical-board scene payload to send to the backend.
 * Strips the client-side-generated `id` if it's not a meaningful
 * persistence value, but keeping ids is harmless and helps with re-edit. */
function buildScenePayload(state) {
    return {
        version: 1,
        pitch_kind: 'soccer_full',
        orientation: 'landscape',
        tokens: state.tokens.map((t) => {
            const out = { id: t.id, kind: t.kind, x: t.x, y: t.y };
            if (t.label) out.label = t.label;
            if (t.player_id) out.player_id = t.player_id;
            return out;
        }),
        shapes: state.shapes.map((s) => {
            const out = { id: s.id, kind: s.kind };
            if (s.kind === 'arrow' || s.kind === 'line') {
                out.x1 = s.x1; out.y1 = s.y1; out.x2 = s.x2; out.y2 = s.y2;
            } else if (s.kind === 'zone') {
                out.x = s.x; out.y = s.y; out.w = s.w; out.h = s.h;
            } else if (s.kind === 'label') {
                out.x = s.x; out.y = s.y;
                out.text = s.text || '';
            }
            return out;
        }),
    };
}

/** Mixin attached to `app` in script.js. */
export const tacticalBoardMixin = {

    /** Render a board read-only into a container. */
    renderTacticalBoardInto(container, board, opts = {}) {
        if (!container) return;
        container.innerHTML = renderTacticalBoardSvg(board, opts);
    },

    /** True if a board has at least one token or shape. */
    tacticalBoardHasContent(board) {
        return boardHasContent(board);
    },

    /** Render the read-only SVG markup for a board. Convenience used
     * by the coach + viewer surfaces that compose row HTML directly. */
    tacticalBoardSvg(board, opts = {}) {
        return renderTacticalBoardSvg(board, opts);
    },

    /**
     * Mount the tactical-board section into a container inside the
     * observation composer. The section is self-contained: it
     * displays a preview when a board exists, an "Add tactical board"
     * affordance when none does, and swaps in the editor in-place
     * when the coach clicks Add/Edit.
     *
     * `getBoard()` and `setBoard(scene|null)` are the read/write
     * channel. The composer's onSubmit reads the latest value via
     * `getBoard()` when building the PATCH/POST body.
     */
    mountTacticalBoardSection(container, { initialBoard = null, getBoard, setBoard } = {}) {
        if (!container) return;
        const sectionState = {
            mode: 'preview', // 'preview' | 'editor'
            // Editor working copy — copied on enter, persisted to setBoard on exit.
            tokens: [],
            shapes: [],
            selectedId: null,
            activeTool: null,
            pendingShape: null,
        };
        // Load from outside on first mount.
        const seed = normalizeBoardForRender(initialBoard);
        if (seed) {
            sectionState.tokens = seed.tokens.map((t) => ({ ...t }));
            sectionState.shapes = seed.shapes.map((s) => ({ ...s }));
        }
        const renderPreviewMode = () => {
            const board = getBoard();
            const has = boardHasContent(board);
            container.innerHTML = '';
            container.className = 'tb-section tb-section--preview';
            const head = document.createElement('div');
            head.className = 'tb-section-head';
            head.innerHTML = `
                <div class="tb-section-title">
                    <span class="tb-section-glyph" aria-hidden="true">⌬</span>
                    <strong>Tactical board</strong>
                    ${has ? '<span class="coach-observation-board-pill">Attached</span>' : '<span class="tb-section-hint">No board yet</span>'}
                </div>
                <div class="tb-section-actions">
                    ${has
                        ? `<button type="button" class="tb-section-btn" data-tb-action="edit">Edit board</button>
                           <button type="button" class="tb-section-btn tb-section-btn--danger" data-tb-action="remove">Remove board</button>`
                        : `<button type="button" class="tb-section-btn" data-tb-action="add">+ Add tactical board</button>`}
                </div>
                <!-- Local confirm bar: NOT a global app modal. The
                     observation composer is itself a formModal and
                     openAppModal is single-active — opening a nested
                     confirm modal would close the parent and lose
                     every coach-typed field. -->
                <div class="tb-confirm-bar" data-tb-confirm hidden role="alertdialog" aria-live="polite"></div>
            `;
            container.appendChild(head);
            if (has) {
                const previewWrap = document.createElement('div');
                previewWrap.className = 'tb-section-preview';
                previewWrap.innerHTML = renderTacticalBoardSvg(board, { size: 'preview' });
                container.appendChild(previewWrap);
            } else {
                const helper = document.createElement('p');
                helper.className = 'tb-section-helper';
                helper.textContent = 'Sketch a quick soccer-pitch scene — players, ball, arrows, zones, and labels. The board attaches to this observation note and follows the same visibility rules.';
                container.appendChild(helper);
            }
            head.querySelector('[data-tb-action="add"]')?.addEventListener('click', () => enterEditor());
            head.querySelector('[data-tb-action="edit"]')?.addEventListener('click', () => enterEditor());
            head.querySelector('[data-tb-action="remove"]')?.addEventListener('click', async () => {
                const confirmed = await runLocalConfirm(head.querySelector('[data-tb-confirm]'), {
                    message: 'Remove the tactical board from this observation? The note itself stays.',
                    confirmLabel: 'Remove board',
                });
                if (!confirmed) return;
                sectionState.tokens = [];
                sectionState.shapes = [];
                setBoard(null);
                renderPreviewMode();
            });
        };

        const enterEditor = () => {
            // Refresh editor working copy from the current saved value
            // (so cancel-without-save behaves as expected).
            const current = getBoard();
            const seed2 = normalizeBoardForRender(current);
            if (seed2) {
                sectionState.tokens = seed2.tokens.map((t) => ({ ...t }));
                sectionState.shapes = seed2.shapes.map((s) => ({ ...s }));
            } else {
                sectionState.tokens = [];
                sectionState.shapes = [];
            }
            sectionState.mode = 'editor';
            sectionState.selectedId = null;
            sectionState.activeTool = null;
            sectionState.pendingShape = null;
            renderEditorMode();
        };

        const exitEditor = ({ save }) => {
            if (save) {
                const payload = buildScenePayload(sectionState);
                if (payload.tokens.length || payload.shapes.length) {
                    setBoard(payload);
                } else {
                    // Saving an empty editor clears the board (matches Remove).
                    setBoard(null);
                }
            }
            sectionState.mode = 'preview';
            renderPreviewMode();
        };

        const renderEditorMode = () => {
            container.innerHTML = '';
            container.className = 'tb-section tb-section--editor';
            const head = document.createElement('div');
            head.className = 'tb-section-head';
            head.innerHTML = `
                <div class="tb-section-title">
                    <span class="tb-section-glyph" aria-hidden="true">⌬</span>
                    <strong>Tactical board editor</strong>
                    <span class="tb-section-hint">Soccer · landscape</span>
                </div>
                <div class="tb-section-actions">
                    <button type="button" class="tb-section-btn" data-tb-action="cancel">Cancel</button>
                    <button type="button" class="tb-section-btn tb-section-btn--primary" data-tb-action="done">Done</button>
                </div>
                <!-- Local confirm bar (see preview mode for rationale). -->
                <div class="tb-confirm-bar" data-tb-confirm hidden role="alertdialog" aria-live="polite"></div>
            `;
            container.appendChild(head);
            const editorRoot = document.createElement('div');
            editorRoot.className = 'tb-editor';
            editorRoot.innerHTML = `
                <div class="tb-toolbar" role="toolbar" aria-label="Tactical board tools">
                    <div class="tb-tool-group" role="group" aria-label="Add to pitch">
                        <button type="button" class="tb-tool-btn" data-tb-tool="player" aria-pressed="false" aria-label="Add player token" title="Add player token">+ Player</button>
                        <button type="button" class="tb-tool-btn" data-tb-tool="ball" aria-pressed="false" aria-label="Add ball" title="Add ball">+ Ball</button>
                        <button type="button" class="tb-tool-btn" data-tb-tool="arrow" aria-pressed="false" aria-label="Add arrow" title="Add arrow">+ Arrow</button>
                        <button type="button" class="tb-tool-btn" data-tb-tool="zone" aria-pressed="false" aria-label="Add zone" title="Add zone">+ Zone</button>
                        <button type="button" class="tb-tool-btn" data-tb-tool="label" aria-pressed="false" aria-label="Add text label" title="Add text label using the Label text field">+ Label</button>
                    </div>
                    <div class="tb-tool-group" role="group" aria-label="Text inputs">
                        <label class="tb-token-label-wrap">
                            <span class="tb-token-label-text">Next player #</span>
                            <input type="text" class="tb-token-label-input" data-tb-input="player-label" maxlength="24" placeholder="e.g. 7" aria-label="Label for next player token">
                        </label>
                        <label class="tb-token-label-wrap">
                            <span class="tb-token-label-text">Label text</span>
                            <input type="text" class="tb-token-label-input" data-tb-input="label-text" maxlength="80" placeholder="e.g. press here" aria-label="Text for the next label">
                        </label>
                    </div>
                    <div class="tb-tool-group tb-tool-group--right" role="group" aria-label="Edit selection">
                        <button type="button" class="tb-tool-btn tb-tool-btn--danger" data-tb-action="delete" disabled aria-label="Delete selected item">Delete selected</button>
                        <button type="button" class="tb-tool-btn tb-tool-btn--danger" data-tb-action="clear" aria-label="Clear all items from the board">Clear board</button>
                    </div>
                </div>
                <p class="tb-helper">
                    Tap a tool, then tap the pitch to add. Arrows and zones use two clicks (start, then end). Drag tokens or shapes to reposition. Click an item to select it, then press Delete or use the toolbar. For labels, type into the <strong>Label text</strong> field first, then click the pitch.
                </p>
                <div class="tb-stage" data-tb-stage></div>
                <p class="tb-status" data-tb-status aria-live="polite"></p>
            `;
            container.appendChild(editorRoot);

            const stage = editorRoot.querySelector('[data-tb-stage]');
            const statusEl = editorRoot.querySelector('[data-tb-status]');
            const playerLabelInput = editorRoot.querySelector('[data-tb-input="player-label"]');
            const labelTextInput = editorRoot.querySelector('[data-tb-input="label-text"]');
            const deleteBtn = editorRoot.querySelector('[data-tb-action="delete"]');
            const toolButtons = Array.from(editorRoot.querySelectorAll('.tb-tool-btn[data-tb-tool]'));
            const confirmBar = head.querySelector('[data-tb-confirm]');
            const setStatus = (msg) => { statusEl.textContent = msg || ''; };

            const refresh = () => {
                stage.innerHTML = renderTacticalBoardSvg(
                    { pitch_kind: 'soccer_full', tokens: sectionState.tokens, shapes: sectionState.shapes },
                    { editor: true, selectedId: sectionState.selectedId, size: 'full' },
                );
                attachStageHandlers();
                deleteBtn.disabled = !sectionState.selectedId;
            };

            const setActiveTool = (tool) => {
                sectionState.activeTool = tool;
                sectionState.pendingShape = null;
                toolButtons.forEach((btn) => {
                    const on = btn.dataset.tbTool === tool;
                    btn.classList.toggle('is-active', on);
                    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
                });
                if (tool === 'arrow' || tool === 'line') setStatus('Click the pitch to set the arrow start.');
                else if (tool === 'zone') setStatus('Click the pitch to set one zone corner, then click the opposite corner.');
                else if (tool === 'player') setStatus('Click the pitch to drop a player token.');
                else if (tool === 'ball') setStatus('Click the pitch to drop the ball.');
                else if (tool === 'label') setStatus('Click the pitch to add a text label.');
                else setStatus('');
            };

            toolButtons.forEach((btn) => {
                btn.addEventListener('click', (event) => {
                    event.preventDefault();
                    if (btn.classList.contains('is-active')) setActiveTool(null);
                    else setActiveTool(btn.dataset.tbTool);
                });
            });

            deleteBtn.addEventListener('click', (event) => {
                event.preventDefault();
                if (!sectionState.selectedId) return;
                sectionState.tokens = sectionState.tokens.filter((t) => t.id !== sectionState.selectedId);
                sectionState.shapes = sectionState.shapes.filter((s) => s.id !== sectionState.selectedId);
                sectionState.selectedId = null;
                refresh();
                setStatus('Item deleted.');
            });

            editorRoot.querySelector('[data-tb-action="clear"]').addEventListener('click', async (event) => {
                event.preventDefault();
                if (!sectionState.tokens.length && !sectionState.shapes.length) return;
                const confirmed = await runLocalConfirm(confirmBar, {
                    message: 'Clear every token and shape from the editor? You can still Cancel to discard, or Done to save.',
                    confirmLabel: 'Clear board',
                });
                if (!confirmed) return;
                sectionState.tokens = [];
                sectionState.shapes = [];
                sectionState.selectedId = null;
                refresh();
                setStatus('Board cleared.');
            });

            editorRoot.addEventListener('keydown', (event) => {
                if ((event.key === 'Delete' || event.key === 'Backspace') && sectionState.selectedId) {
                    // Don't intercept while typing in either text input.
                    if (event.target === playerLabelInput || event.target === labelTextInput) return;
                    event.preventDefault();
                    deleteBtn.click();
                }
            });

            head.querySelector('[data-tb-action="cancel"]').addEventListener('click', () => exitEditor({ save: false }));
            head.querySelector('[data-tb-action="done"]').addEventListener('click', () => exitEditor({ save: true }));

            const pitchPointFromEvent = (event) => {
                const svg = stage.querySelector('svg.tb-svg');
                if (!svg) return null;
                const rect = svg.getBoundingClientRect();
                const x = (event.clientX - rect.left) / rect.width;
                const y = (event.clientY - rect.top) / rect.height;
                return { x: clamp01(x), y: clamp01(y) };
            };

            const attachStageHandlers = () => {
                const svg = stage.querySelector('svg.tb-svg');
                if (!svg) return;
                // Idempotency guard — refresh() rebuilds the SVG via
                // innerHTML which discards the previous element AND
                // its listeners, but mark the new one anyway so a
                // future caller that bypasses refresh() can't double-
                // bind on the same SVG.
                if (svg.dataset.tbStageBound === '1') return;
                svg.dataset.tbStageBound = '1';
                svg.addEventListener('mousedown', onPointerDown);
                svg.addEventListener('touchstart', onPointerDown, { passive: false });
            };

            const onPointerDown = (event) => {
                const target = event.target.closest('[data-token-id], [data-shape-id]');
                if (target) {
                    const id = target.dataset.tokenId || target.dataset.shapeId;
                    sectionState.selectedId = id;
                    sectionState.pendingShape = null;
                    refresh();
                    setStatus('Selected. Drag to move, press Delete or use the toolbar to remove.');
                    beginDrag(event, target);
                    return;
                }
                if (!sectionState.activeTool) {
                    sectionState.selectedId = null;
                    refresh();
                    return;
                }
                event.preventDefault();
                const pt = pitchPointFromEvent(event.touches ? event.touches[0] : event);
                if (!pt) return;
                applyToolClick(pt);
            };

            const applyToolClick = (pt) => {
                const tool = sectionState.activeTool;
                if (tool === 'player') {
                    if (sectionState.tokens.length >= 40) { setStatus('Player limit reached (40 tokens).'); return; }
                    const label = (playerLabelInput.value || '').trim().slice(0, 24);
                    sectionState.tokens.push({ id: nextId('token'), kind: 'player', x: pt.x, y: pt.y, label, player_id: '' });
                    if (label) playerLabelInput.value = '';
                    refresh();
                    setStatus('Player added.');
                } else if (tool === 'ball') {
                    if (sectionState.tokens.length >= 40) { setStatus('Token limit reached (40).'); return; }
                    sectionState.tokens.push({ id: nextId('token'), kind: 'ball', x: pt.x, y: pt.y, label: '', player_id: '' });
                    setActiveTool(null);
                    refresh();
                    setStatus('Ball added.');
                } else if (tool === 'arrow' || tool === 'line') {
                    if (sectionState.shapes.length >= 40) { setStatus('Shape limit reached (40).'); return; }
                    if (!sectionState.pendingShape) {
                        sectionState.pendingShape = { kind: tool, x1: pt.x, y1: pt.y };
                        setStatus('Now click the arrow end point.');
                    } else {
                        sectionState.shapes.push({
                            id: nextId('shape'), kind: sectionState.pendingShape.kind,
                            x1: sectionState.pendingShape.x1, y1: sectionState.pendingShape.y1,
                            x2: pt.x, y2: pt.y,
                        });
                        sectionState.pendingShape = null;
                        refresh();
                        setStatus(`${tool === 'arrow' ? 'Arrow' : 'Line'} added.`);
                    }
                } else if (tool === 'zone') {
                    if (sectionState.shapes.length >= 40) { setStatus('Shape limit reached (40).'); return; }
                    if (!sectionState.pendingShape) {
                        sectionState.pendingShape = { kind: 'zone', x1: pt.x, y1: pt.y };
                        setStatus('Now click the opposite corner of the zone.');
                    } else {
                        const x = Math.min(sectionState.pendingShape.x1, pt.x);
                        const y = Math.min(sectionState.pendingShape.y1, pt.y);
                        const w = Math.max(0.05, Math.abs(sectionState.pendingShape.x1 - pt.x));
                        const h = Math.max(0.05, Math.abs(sectionState.pendingShape.y1 - pt.y));
                        sectionState.shapes.push({
                            id: nextId('shape'), kind: 'zone',
                            x, y,
                            w: Math.min(w, 1 - x),
                            h: Math.min(h, 1 - y),
                        });
                        sectionState.pendingShape = null;
                        refresh();
                        setStatus('Zone added.');
                    }
                } else if (tool === 'label') {
                    if (sectionState.shapes.length >= 40) { setStatus('Shape limit reached (40).'); return; }
                    // Read label text from the inline toolbar input
                    // instead of window.prompt (per project policy: no
                    // raw browser dialogs / chrome). When empty, focus
                    // the input and prompt the user inline.
                    const trimmed = (labelTextInput.value || '').trim().slice(0, 80);
                    if (!trimmed) {
                        labelTextInput.focus();
                        setStatus('Type label text in the Label text field, then click the pitch.');
                        return;
                    }
                    sectionState.shapes.push({ id: nextId('shape'), kind: 'label', x: pt.x, y: pt.y, text: trimmed });
                    labelTextInput.value = '';
                    setActiveTool(null);
                    refresh();
                    setStatus('Label added.');
                }
            };

            const beginDrag = (downEvent, target) => {
                const id = target.dataset.tokenId || target.dataset.shapeId;
                const isToken = !!target.dataset.tokenId;
                const item = isToken
                    ? sectionState.tokens.find((t) => t.id === id)
                    : sectionState.shapes.find((s) => s.id === id);
                if (!item) return;
                const startPt = pitchPointFromEvent(downEvent.touches ? downEvent.touches[0] : downEvent);
                if (!startPt) return;
                const original = JSON.parse(JSON.stringify(item));
                let didMove = false;
                const move = (event) => {
                    event.preventDefault();
                    const pt = pitchPointFromEvent(event.touches ? event.touches[0] : event);
                    if (!pt) return;
                    const dx = pt.x - startPt.x;
                    const dy = pt.y - startPt.y;
                    if (Math.abs(dx) + Math.abs(dy) > 0.005) didMove = true;
                    if (isToken) {
                        item.x = clamp01(original.x + dx);
                        item.y = clamp01(original.y + dy);
                    } else if (item.kind === 'arrow' || item.kind === 'line') {
                        item.x1 = clamp01(original.x1 + dx);
                        item.y1 = clamp01(original.y1 + dy);
                        item.x2 = clamp01(original.x2 + dx);
                        item.y2 = clamp01(original.y2 + dy);
                    } else if (item.kind === 'zone') {
                        const nx = clamp01(original.x + dx);
                        const ny = clamp01(original.y + dy);
                        item.x = Math.min(nx, 1 - original.w);
                        item.y = Math.min(ny, 1 - original.h);
                    } else if (item.kind === 'label') {
                        item.x = clamp01(original.x + dx);
                        item.y = clamp01(original.y + dy);
                    }
                    refresh();
                };
                const up = () => {
                    window.removeEventListener('mousemove', move);
                    window.removeEventListener('mouseup', up);
                    window.removeEventListener('touchmove', move);
                    window.removeEventListener('touchend', up);
                    if (didMove) setStatus('Item moved.');
                };
                window.addEventListener('mousemove', move);
                window.addEventListener('mouseup', up);
                window.addEventListener('touchmove', move, { passive: false });
                window.addEventListener('touchend', up);
            };

            refresh();
        };

        // Initial paint.
        renderPreviewMode();
    },
};
