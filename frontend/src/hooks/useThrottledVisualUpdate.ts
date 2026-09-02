import { useCallback, useLayoutEffect, useRef } from 'react'

const DEFAULT_INTERVAL_FRAMES = 3

/**
 * 把「非关键的视觉对齐」合并到隔 N 帧执行一次（移植自 deepseek-harness 的
 * `useThrottledVisualUpdate`）。
 *
 * 用途：思考行的摘要要跟随尾部滚动（`scrollLeft = scrollWidth - clientWidth`）。
 * 流式每 ~800ms 来一次增量、打字机每 40ms 一帧，直接在 effect 里改 DOM 会把每次
 * 渲染都变成一次强制同步布局。这类对齐晚几帧完全无感，但省下的是每帧的 reflow。
 *
 * 卸载时取消未决帧——组件在流式中途消失（终稿到达）是常态，不取消会留下一个
 * 指向已卸载节点的回调。
 */
export function useThrottledVisualUpdate(
  update: () => void,
  intervalFrames = DEFAULT_INTERVAL_FRAMES,
): () => void {
  const updateRef = useRef(update)
  updateRef.current = update
  const pendingFrameRef = useRef<number | null>(null)

  useLayoutEffect(() => () => {
    if (pendingFrameRef.current === null) return
    cancelAnimationFrame(pendingFrameRef.current)
    pendingFrameRef.current = null
  }, [])

  return useCallback(() => {
    if (pendingFrameRef.current !== null) return
    let remainingFrames = intervalFrames
    const advance = (): void => {
      remainingFrames -= 1
      if (remainingFrames > 0) {
        pendingFrameRef.current = requestAnimationFrame(advance)
        return
      }
      pendingFrameRef.current = null
      updateRef.current()
    }
    pendingFrameRef.current = requestAnimationFrame(advance)
  }, [intervalFrames])
}
