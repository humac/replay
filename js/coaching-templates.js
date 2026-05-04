// Phase 2 — static coach review templates.
//
// Reusable starter content for common soccer coaching moments. Each
// template prefills the structured note fields the coach would
// otherwise type by hand:
//
//   title, category, note_type, player_summary,
//   what_happened, why_it_matters, what_to_do_next, tags
//
// Templates are intentionally NOT wired up to populate
// `coach_private_note` — that field stays empty unless the coach
// types into it themselves. See `.agent-skills/coaching-data-privacy.md`.
//
// The registry is a plain ES-module export consumed by `js/coaching.js`.
// It does NOT register a mixin; templates are static data, not behavior.
//
// Storage strategy: per the Phase 2 spec, this is a static frontend
// registry. Future phases may move templates to DB-backed customisable
// rows — when that happens, replace the `COACH_TEMPLATES` constant with
// a fetched array but keep the same shape.
//
// Field shape (every template has all keys, even if empty):
//   id            — stable kebab-case slug, never reused
//   label         — coach-facing name shown in the selector
//   group         — coach-facing group/category (drives <optgroup>)
//   category      — backend `category` value (must be in NOTE_CATEGORIES)
//   note_type     — backend `note_type` value (must be in NOTE_TYPES)
//   title         — suggested note title
//   player_summary    — short, age-appropriate player-facing line
//   what_happened     — prompt for the observation
//   why_it_matters    — prompt for the coaching context
//   what_to_do_next   — prompt for the actionable next step
//   tags          — array of suggested tags (lowercased, no spaces)
//
// Template content is intentionally generic — the coach edits the text
// to fit the actual moment before saving.

export const COACH_TEMPLATES = [
    // ===== Build-up =====
    {
        id: 'scanning-before-receiving',
        label: 'Scanning before receiving',
        group: 'Build-up',
        category: 'build_up',
        note_type: 'team_concept',
        title: 'Scan before the ball arrives',
        player_summary: 'Two quick looks before the ball reaches you so you already know your next pass.',
        what_happened: 'You received the pass without having scanned the space behind and beside you.',
        why_it_matters: 'A scan a beat earlier shows you the open teammate and turns a square pass into a forward one.',
        what_to_do_next: 'Look over both shoulders just before the pass leaves your teammate, then again as the ball travels.',
        tags: ['scanning', 'awareness', 'receiving'],
    },
    {
        id: 'body-shape-when-receiving',
        label: 'Body shape when receiving',
        group: 'Build-up',
        category: 'build_up',
        note_type: 'individual_goal',
        title: 'Open body shape when receiving',
        player_summary: 'Open up across your body so your first touch already faces the goal you are attacking.',
        what_happened: 'You received with your body square to the passer, which forced a back pass under pressure.',
        why_it_matters: 'Open hips let you play forward with one touch instead of turning under defenders.',
        what_to_do_next: 'Plant the back foot, point the front foot toward the opponent goal, take the touch with the far foot.',
        tags: ['body-shape', 'receiving', 'first-touch'],
    },
    {
        id: 'first-touch-direction',
        label: 'First touch direction',
        group: 'Build-up',
        category: 'build_up',
        note_type: 'correction',
        title: 'First touch into space',
        player_summary: 'Push your first touch into the space you want to attack, not back to the passer.',
        what_happened: 'First touch went straight back to the centre instead of out into the wide channel.',
        why_it_matters: 'A directional first touch gets you past the closest defender before they can adjust.',
        what_to_do_next: 'Decide your next move before the ball arrives. Cushion the touch into the lane you already chose.',
        tags: ['first-touch', 'receiving', 'direction'],
    },
    {
        id: 'passing-decision',
        label: 'Passing decision',
        group: 'Build-up',
        category: 'decision',
        note_type: 'question',
        title: 'Passing decision under pressure',
        player_summary: 'Look for the higher-value pass first — forward, then sideways, then back.',
        what_happened: 'You played a safe back pass when a forward option was open between the lines.',
        why_it_matters: 'Forward passes break a line of pressure and create chances. Back passes reset the attack.',
        what_to_do_next: 'Scan the line ahead of you first. If the forward pass is on, take it. Reset only if it is not.',
        tags: ['passing', 'decision', 'progression'],
    },
    {
        id: 'movement-after-pass',
        label: 'Movement after pass',
        group: 'Build-up',
        category: 'build_up',
        note_type: 'team_concept',
        title: 'Move after you pass',
        player_summary: 'After the pass, move into a new space — give and go, overlap, or rotate.',
        what_happened: 'You passed and stood still, taking yourself out of the next phase.',
        why_it_matters: 'A passer who moves becomes a new option a beat later. A passer who stops becomes a defender to ignore.',
        what_to_do_next: 'Pick one of: give-and-go, overlap, underlap, or drop into a new line. Move within two seconds of the pass.',
        tags: ['movement', 'pass-and-move', 'support'],
    },

    // ===== Shape =====
    {
        id: 'width-and-depth',
        label: 'Width and depth',
        group: 'Shape',
        category: 'shape',
        note_type: 'team_concept',
        title: 'Stretch the field — width and depth',
        player_summary: 'Stay wide and high to stretch their defenders apart and open the middle.',
        what_happened: 'The team collapsed into a tight cluster around the ball, removing the space we want to play into.',
        why_it_matters: 'Width pulls their defenders out, depth pushes them back. The space between is where chances live.',
        what_to_do_next: 'Wide players hug the touchline. Forwards stay on the last shoulder. Only collapse in to combine, then sprint out again.',
        tags: ['shape', 'spacing', 'width', 'depth'],
    },

    // ===== Defending =====
    {
        id: 'defensive-recovery',
        label: 'Defensive recovery',
        group: 'Defending',
        category: 'defending',
        note_type: 'positive',
        title: 'Defensive recovery run',
        player_summary: 'Strong recovery — you cut across the passing lane instead of chasing the ball.',
        what_happened: 'After we lost possession, you sprinted on a recovery angle that closed the inside lane behind our defence.',
        why_it_matters: 'Cutting across the lane prevents the through ball; chasing the ball just lets the runner go past you.',
        what_to_do_next: 'Keep this exact angle as the model. The first three steps are everything — sprint, do not jog.',
        tags: ['recovery', 'transition', 'defending'],
    },
    {
        id: 'pressing-trigger',
        label: 'Pressing trigger',
        group: 'Defending',
        category: 'pressing',
        note_type: 'team_concept',
        title: 'Pressing trigger — front three together',
        player_summary: 'When their keeper plants the ball, step up together and cut the short pass.',
        what_happened: 'Their keeper had an easy short option because our front three pressed at different times.',
        why_it_matters: 'A synchronised press forces long balls into our centre-backs — that is a 70% recovery rate for us.',
        what_to_do_next: 'Watch your wide partner first step. When they go, you go. Body shape closes the inside, not the keeper.',
        tags: ['pressing', 'trigger', 'team-press'],
    },
    {
        id: 'delay-contain-1v1',
        label: 'Delay / contain in 1v1 defending',
        group: 'Defending',
        category: 'defending',
        note_type: 'correction',
        title: 'Delay and contain — do not dive in',
        player_summary: 'When you defend 1v1, slow the attacker down and wait for help.',
        what_happened: 'You committed to the tackle early and the attacker beat you with one touch.',
        why_it_matters: 'Most 1v1 wins come from delaying long enough for a teammate to arrive, not from a clean steal.',
        what_to_do_next: 'Get goalside. Stay low. Show them onto their weaker foot. Tackle only when they take a heavy touch.',
        tags: ['defending', '1v1', 'delay'],
    },
    {
        id: 'tracking-runner',
        label: 'Tracking runner',
        group: 'Defending',
        category: 'defending',
        note_type: 'correction',
        title: 'Track the runner all the way',
        player_summary: 'When your mark moves into space, go with them — do not pass them on.',
        what_happened: 'A runner from midfield went past you unmarked into the box.',
        why_it_matters: 'Late runners cause the most goals. Once the line breaks, no one knows whose mark they are.',
        what_to_do_next: 'Eyes on ball AND runner. If they go, you go — and shout to a teammate if you need a swap.',
        tags: ['marking', 'tracking', 'late-runs'],
    },

    // ===== Goalkeeper =====
    {
        id: 'goalkeeper-distribution',
        label: 'Goalkeeper distribution',
        group: 'Goalkeeper',
        category: 'goalkeeper',
        note_type: 'individual_goal',
        title: 'Goalkeeper distribution choice',
        player_summary: 'Pick the distribution that matches the pressure and the open teammate.',
        what_happened: 'Distribution was rushed — long when a short option was open, or short into pressure.',
        why_it_matters: 'A keeper who picks the right pass starts attacks. A keeper who panics gives the ball back.',
        what_to_do_next: 'Scan first. If the centre-back is free, roll it short. If they are pressed, find the wide outlet or go long.',
        tags: ['goalkeeper', 'distribution', 'build-up'],
    },

    // ===== Set pieces =====
    {
        id: 'set-piece-marking',
        label: 'Set-piece marking',
        group: 'Set piece',
        category: 'set_piece',
        note_type: 'team_concept',
        title: 'Set-piece marking assignments',
        player_summary: 'Know your mark before the kick is taken and stay tight to them.',
        what_happened: 'A runner found space inside the six-yard box because their assignment was unclear.',
        why_it_matters: 'Set-piece goals come from one moment of confusion. Clarity beats athleticism here.',
        what_to_do_next: 'Confirm your mark out loud before every set piece. Start touch-tight, not arms-length.',
        tags: ['set-piece', 'marking', 'defending'],
    },

    // ===== Transition =====
    {
        id: 'transition-reaction',
        label: 'Transition reaction',
        group: 'Transition',
        category: 'transition',
        note_type: 'team_concept',
        title: 'First five seconds after a turnover',
        player_summary: 'The first five seconds after we win or lose the ball decide the next chance.',
        what_happened: 'We took too long to react after the turnover — either to press immediately or to break out.',
        why_it_matters: 'Transition is when the opponent is most disorganised. The team that reacts first wins the next phase.',
        what_to_do_next: 'On lose: nearest two press, everyone else slides. On win: first thought is forward — can we break?',
        tags: ['transition', 'reaction', 'tempo'],
    },

    // ===== Finishing =====
    {
        id: 'finishing-choice',
        label: 'Finishing choice',
        group: 'Finishing',
        category: 'finishing',
        note_type: 'individual_goal',
        title: 'Pick the right finish',
        player_summary: 'Pick the finish that fits the angle, distance, and keeper position.',
        what_happened: 'You picked a power finish when placement into the far corner was the higher-percentage choice.',
        why_it_matters: 'Smart strikers convert more chances by choosing the right finish, not the most spectacular one.',
        what_to_do_next: 'Scan the keeper position as you set up. Side-foot for placement. Laces for power. Chip if they are off the line.',
        tags: ['finishing', 'composure', 'decision'],
    },
];

// Export a flat list of group names in the order they should appear in
// the selector. Templates inside a group preserve their array order.
export const COACH_TEMPLATE_GROUPS = (() => {
    const seen = new Set();
    const ordered = [];
    for (const t of COACH_TEMPLATES) {
        if (!seen.has(t.group)) {
            seen.add(t.group);
            ordered.push(t.group);
        }
    }
    return ordered;
})();

// Look up a template by id. Returns `null` for unknown ids so callers
// don't have to defensively check `.find`.
export function findCoachTemplate(id) {
    if (!id) return null;
    return COACH_TEMPLATES.find((t) => t.id === id) || null;
}
