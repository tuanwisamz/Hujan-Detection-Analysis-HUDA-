/** "nowcast_rate>=30" -> plain-language reason (spec §10.2 Problem-solving: show why). */
export function describeRule(rule, t, th = {}) {
  if (!rule) return null
  const [name, value] = rule.split('>=')
  const pct = (f, d) => Math.round((f ?? d) * 100)
  if (name === 'nowcast_rate') {
    // The amber rate is a single pixel; the RED very-heavy rule needs area and duration (v2 D16)
    if (Number(value) >= (th.very_heavy_mmh ?? 60))
      return t('rule.nowcast_very_heavy', { v: value, min: th.very_heavy_duration_min ?? 20 })
    return t('rule.nowcast_rate', { v: value })
  }
  if (name === 'nowcast_sustained')
    return t('rule.nowcast_sustained', { v: value, area: pct(th.red_area_frac, 0.2), min: th.red_duration_min ?? 30 })
  if (name === 'p_ml') return t('rule.p_ml', { v: Math.round(Number(value) * 100) })
  if (['accum_24h', 'nowcast_accum_1h', 'gauge_1h', 'gauge_3h'].includes(name)) return t(`rule.${name}`, { v: value })
  return t(`rule.${name}`)
}
