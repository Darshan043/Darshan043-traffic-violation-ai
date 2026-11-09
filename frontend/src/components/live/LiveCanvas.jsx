import { useEffect, useRef } from 'react'

export default function LiveCanvas({ cameraName = 'Camera' }) {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current
    const context = canvas?.getContext('2d')
    if (!context) return undefined
    let frame
    let width = 0
    let height = 0
    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      const ratio = window.devicePixelRatio || 1
      width = rect.width
      height = rect.height
      canvas.width = Math.max(1, Math.floor(width * ratio))
      canvas.height = Math.max(1, Math.floor(height * ratio))
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    const draw = (time) => {
      context.clearRect(0, 0, width, height)
      const sky = context.createLinearGradient(0, 0, 0, height)
      sky.addColorStop(0, '#233a4c'); sky.addColorStop(.56, '#516777'); sky.addColorStop(1, '#182c39')
      context.fillStyle = sky; context.fillRect(0, 0, width, height)
      context.fillStyle = '#263b48'; context.fillRect(0, height * .59, width, height * .41)
      context.strokeStyle = 'rgba(224,236,241,.35)'; context.setLineDash([18, 15]); context.lineWidth = 2
      context.beginPath(); context.moveTo(width * .5, height * .62); context.lineTo(width * .5, height); context.stroke(); context.setLineDash([])
      context.fillStyle = 'rgba(215,231,237,.76)'; context.font = '11px system-ui'; context.fillText(`${cameraName.toUpperCase()} · MOCK LIVE`, 16, 22)
      for (let index = 0; index < 3; index += 1) {
        const w = width * (.105 + index * .018)
        const h = height * (.25 + index * .035)
        const x = ((time * (.018 + index * .006) + index * width * .37) % (width + w)) - w
        const y = height * (.55 - index * .075)
        context.strokeStyle = index === 1 ? '#f5bd57' : '#4fe0ae'; context.lineWidth = 2
        context.strokeRect(x, y - h, w, h)
        context.fillStyle = index === 1 ? '#f5bd57' : '#4fe0ae'; context.fillRect(x, y - h - 18, Math.min(78, w), 16)
        context.fillStyle = '#142c35'; context.font = '10px system-ui'; context.fillText(`ID ${21 + index}`, x + 4, y - h - 6)
      }
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(frame); observer.disconnect() }
  }, [cameraName])
  return <canvas ref={ref} className="live-canvas" aria-label={`Animated mock traffic view for ${cameraName}`} role="img" />
}
