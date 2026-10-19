/** "nowcast_rate>=30" -> plain-language reason (spec §10.2 Problem-solving: show why). */
export function describeRule(rule, t) {
  if (!rule) return null
  const [name, value] = rule.split('>=')
  if (name === 'nowcast_rate') return t('rule.nowcast_rate', { v: value })
  if (name === 'p_ml') return t('rule.p_ml', { v: Math.round(Number(value) * 100) })
  if (name === 'accum_24h') return t('rule.accum_24h', { v: value })
  return t(`rule.${name}`)
}
