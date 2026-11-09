export function pixelsToNormalized(points, width, height) {
  if (!width || !height) return []
  return points.map(([x, y]) => [
    Number(Math.max(0, Math.min(1, x / width)).toFixed(4)),
    Number(Math.max(0, Math.min(1, y / height)).toFixed(4)),
  ])
}

export function normalizedToPixels(points, width, height) {
  return points.map(([x, y]) => [x * width, y * height])
}
