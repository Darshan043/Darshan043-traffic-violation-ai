const roleActions = {
  admin: new Set(['*']),
  reviewer: new Set(['view', 'review', 'export']),
  viewer: new Set(['view']),
}

// Client role checks improve navigation and usability; the backend must enforce every permission.
export function can(role, action) {
  const allowed = roleActions[role]
  return Boolean(allowed && (allowed.has('*') || allowed.has(action)))
}
