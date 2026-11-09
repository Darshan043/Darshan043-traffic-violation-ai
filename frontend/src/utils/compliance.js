// Needs-review events are excluded by accepting only compliant and violation counts.
export function calculateCompliance(compliant, violations) {
  const compliantCount = Number(compliant) || 0
  const violationCount = Number(violations) || 0
  const decidedCount = compliantCount + violationCount
  return decidedCount === 0 ? 0 : (compliantCount / decidedCount) * 100
}
