// 全站按压反馈：按下形变 + 波纹 + 安卓 App 触感。main.tsx 安装一次，组件无需改动。
// 波纹画在 body 上与按钮重合的 fixed 容器里，不往按钮内部插节点、不改它的 position/overflow，
// 所以不会碰到任何现有布局；形变用独立的 `scale` 属性，不覆盖元素已有的 transform。

export const PRESS_SELECTOR = 'button, [role="button"], [role="tab"], [role="switch"], a.btn, summary'
// 面积超过它的卡片只轻微下沉，否则整张大卡缩 4% 会显得在「跳」。
export const LARGE_PRESS_AREA = 160 * 64
export type HapticKind = 'tick' | 'confirm' | 'reject'

interface Rect { left: number; top: number; width: number; height: number }

/** 波纹圆：以按下点为圆心，半径够盖住按钮最远的角。坐标相对按钮左上角。 */
export function rippleGeometry(rect: Rect, x: number, y: number) {
  const dx = Math.max(x - rect.left, rect.left + rect.width - x)
  const dy = Math.max(y - rect.top, rect.top + rect.height - y)
  const size = Math.ceil(2 * Math.hypot(dx, dy))
  return { size, left: x - rect.left - size / 2, top: y - rect.top - size / 2 }
}

export function pressSize(rect: Rect): 'sm' | 'lg' {
  return rect.width * rect.height > LARGE_PRESS_AREA ? 'lg' : 'sm'
}

/** 只有切换类控件按下时给轻触；普通按钮每点都震是噪声。 */
export function pressHaptic(el: Element): HapticKind | null {
  const role = el.getAttribute('role')
  if (role === 'tab' || role === 'switch' || el.hasAttribute('aria-pressed') || el.hasAttribute('aria-checked')) return 'tick'
  const opt = el.getAttribute('data-haptic')
  return opt === 'tick' || opt === 'confirm' || opt === 'reject' ? opt : null
}

export function pressTarget(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null
  const el = target.closest<HTMLElement>(PRESS_SELECTOR)
  if (!el || el.closest('[data-no-press]')) return null
  if ((el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true') return null
  return el
}

const isAndroidApp = () => /17TongyouAndroid\//.test(navigator.userAgent) && !!window.TongyouNative

export function nativeHaptic(kind: HapticKind) {
  if (!isAndroidApp()) return
  try { window.TongyouNative?.postMessage(JSON.stringify({ type: 'haptic', kind })) } catch { /* 触感是锦上添花，失败不影响操作 */ }
}

function spawnRipple(el: HTMLElement, x: number, y: number) {
  const rect = el.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const style = getComputedStyle(el)
  const host = document.createElement('span')
  host.className = 'press-ripple-host'
  host.setAttribute('aria-hidden', 'true')
  Object.assign(host.style, {
    left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`,
    borderRadius: style.borderRadius, color: style.color,
  })
  const g = rippleGeometry(rect, x, y)
  const dot = document.createElement('span')
  dot.className = 'press-ripple'
  Object.assign(dot.style, { width: `${g.size}px`, height: `${g.size}px`, left: `${g.left}px`, top: `${g.top}px` })
  host.appendChild(dot)
  document.body.appendChild(host)
  const remove = () => host.remove()
  dot.addEventListener('animationend', remove, { once: true })
  window.setTimeout(remove, 900)
}

let installed = false
export function installPressFeedback() {
  if (installed || typeof document === 'undefined') return
  installed = true
  const reduce = matchMedia('(prefers-reduced-motion: reduce)')
  let pressed: HTMLElement | null = null
  const release = () => { if (pressed) { delete pressed.dataset.pressed; pressed = null } }

  document.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return
    const el = pressTarget(e.target)
    if (!el) return
    const haptic = pressHaptic(el)
    if (haptic) nativeHaptic(haptic)
    if (reduce.matches) return
    release()
    pressed = el
    el.dataset.pressed = pressSize(el.getBoundingClientRect())
    spawnRipple(el, e.clientX, e.clientY)
  }, { passive: true, capture: true })
  for (const type of ['pointerup', 'pointercancel', 'dragstart']) document.addEventListener(type, release, { passive: true, capture: true })
  // 鼠标按住拖出按钮就恢复（触屏开始滚动时浏览器会发 pointercancel）；子元素的 leave 不算。
  document.addEventListener('pointerleave', (e) => { if (e.target === pressed) release() }, { passive: true, capture: true })
  window.addEventListener('blur', release)
}
