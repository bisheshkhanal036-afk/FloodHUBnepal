// Pure helpers converting a criterion's classification state (breaks +
// direction, or per-code risk classes) into the reclassification_rules
// array POST /api/overlay/compute actually expects — kept independent
// of React state, same reasoning as lib/ahpMatrix.js.

/**
 * 4 ascending interior breaks + a direction -> 5 reclassification_rules,
 * matching every hand-written rule set already in config/criteria.js
 * (min_inclusive defaults true, max_inclusive defaults false server-side
 * — see reclassify.py — so continuous rules never need to set those
 * explicitly, unlike categorical ones).
 */
export function breaksToRules(breaks, riskDirection) {
  const edges = [null, ...breaks, null]
  const classes = riskDirection === 'descending' ? [5, 4, 3, 2, 1] : [1, 2, 3, 4, 5]
  return edges.slice(0, -1).map((lo, i) => ({ min: lo, max: edges[i + 1], risk_class: classes[i] }))
}

/**
 * The inverse of breaksToRules, for seeding a criterion's initial break
 * values from its static defaultReclassificationRules: the ordered
 * rules' own `max` values (except the last, unbounded one) are exactly
 * the 4 interior breaks, regardless of risk direction.
 */
export function rulesToBreaks(rules) {
  return rules.slice(0, 4).map((r) => r.max)
}

/**
 * {code: risk_class} -> one categorical point rule per code.
 * min_inclusive/max_inclusive MUST both be explicit true here -- the
 * backend's max_inclusive default is false (correct for a continuous
 * range's upper bound), which makes a min===max point rule match
 * nothing at all. Verified live during an earlier phase: omitting these
 * made every worldcover_land_cover pixel come back "matched no
 * reclassification rule" (a 422 from the real backend).
 */
export function codeClassesToRules(riskClassByCode) {
  return Object.entries(riskClassByCode).map(([code, risk_class]) => ({
    min: Number(code),
    max: Number(code),
    min_inclusive: true,
    max_inclusive: true,
    risk_class,
  }))
}

/** The inverse of codeClassesToRules, for seeding initial per-code classes from static defaults. */
export function rulesToCodeClasses(rules) {
  return Object.fromEntries(rules.map((r) => [r.min, r.risk_class]))
}

/** A fresh classification entry for `criterion`, seeded from its static defaults -- used both when a criterion is first checked and when the AOI changes (breaks/suggestions are AOI-specific, so they reset then). */
export function defaultClassificationEntry(criterion) {
  const isCategorical = criterion.type === 'categorical'
  return {
    method: 'manual',
    breaks: isCategorical ? null : rulesToBreaks(criterion.defaultReclassificationRules),
    riskClassByCode: isCategorical ? rulesToCodeClasses(criterion.defaultReclassificationRules) : null,
    fetch: { status: 'idle', min: null, max: null, equal_interval: null, quantile: null, jenks: null, error: null },
  }
}

/** The reclassification_rules to actually submit for `criterion`, given its current classification entry. */
export function rulesForClassification(criterion, entry) {
  if (!entry) return criterion.defaultReclassificationRules
  if (criterion.type === 'categorical') return codeClassesToRules(entry.riskClassByCode)
  return breaksToRules(entry.breaks, criterion.riskDirection)
}

/**
 * Switches one criterion's classification method to `method` (one of
 * 'equal_interval'/'quantile'/'jenks' -- never 'manual', which has
 * nothing to select). If that method's breaks were already fetched for
 * the current AOI (entry.fetch.status === 'loaded' -- POST /criteria/
 * breaks returns all 3 methods' breaks in one response, so switching
 * between them after the first fetch never needs a second request),
 * applies them immediately; otherwise just sets the method, and
 * ClassificationEditor.jsx's own per-criterion fetch effect (which runs
 * whenever the criterion is checked, regardless of whether its
 * "Customize breaks" <details> is expanded -- a native <details> always
 * mounts its children, just CSS-hides them when closed) picks up the
 * fetch from there.
 *
 * Shared by ClassificationEditor.jsx's own per-criterion method buttons
 * AND CriteriaPanel.jsx's bulk "Auto-classify all" action, so both take
 * the exact same path rather than two copies that could quietly drift
 * apart on this non-obvious "apply already-fetched breaks immediately"
 * behavior.
 */
export function selectClassificationMethod(dispatch, criterionId, method, entry) {
  dispatch({ type: 'SET_CLASSIFICATION_METHOD', id: criterionId, method })
  if (entry.fetch.status === 'loaded' && entry.fetch[method]) {
    dispatch({ type: 'SET_CLASSIFICATION_BREAKS', id: criterionId, breaks: entry.fetch[method] })
  }
}
