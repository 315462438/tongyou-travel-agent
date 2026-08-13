/**
 * 带表情与图片的聊天输入框（Phase 74）——客服会话与行程群聊共用。
 *
 * 表情用 Unicode emoji，不引第三方表情包库：微信那种「自带小表情」用 emoji 完全覆盖，
 * 引库会带进字体/雪碧图/许可一堆事。
 * 图片走 `POST /api/uploads`，消息里以 `![](/travel/api/uploads/{id})` 内联，
 * 由渲染方决定怎么显示。
 */
import { useEffect, useRef, useState } from 'react'
import { API, authFetch } from '../api'
import { shouldSubmitComposer } from '../interaction'

const EMOJI_GROUPS: { label: string; items: string[] }[] = [
  {
    label: '常用',
    items: ['😀', '😄', '😁', '😊', '🙂', '😉', '😍', '🤩', '😘', '😗', '😜', '🤪',
      '🤗', '🤔', '🤨', '😐', '😴', '😌', '😭', '😂', '🥲', '😅', '😳', '🥺',
      '😤', '😡', '🤯', '😱', '🤠', '🥳', '😎', '🤝'],
  },
  {
    label: '手势',
    items: ['👍', '👎', '👌', '✌️', '🤞', '👏', '🙌', '🙏', '💪', '👋', '✍️', '🫰'],
  },
  {
    label: '旅行',
    items: ['✈️', '🚄', '🚗', '🚕', '🏝️', '🏔️', '🗻', '🏕️', '⛺', '🧳', '🗺️', '🧭',
      '📸', '🎒', '🏨', '🎡', '⛩️', '🏯', '🌅', '🌃'],
  },
  {
    label: '美食',
    items: ['🍜', '🍲', '🍢', '🍡', '🍰', '🍦', '🍉', '🍓', '🍇', '🍺', '🍵', '☕',
      '🥘', '🌶️', '🦐', '🦀', '🥟', '🍤'],
  },
  {
    label: '其他',
    items: ['❤️', '💔', '✨', '🔥', '⭐', '🎉', '🎁', '💡', '⚠️', '✅', '❌', '❓',
      '💰', '⏰', '📌', '🔔'],
  },
]

export interface ChatInputProps {
  onSend: (text: string) => void | Promise<void>
  placeholder?: string
  /** 上传失败等提示交给宿主组件展示 */
  onError?: (msg: string) => void
  disabled?: boolean
}

export function ChatInput({ onSend, placeholder = '说点什么…', onError, disabled }: ChatInputProps) {
  const [text, setText] = useState('')
  const [showEmoji, setShowEmoji] = useState(false)
  const [uploading, setUploading] = useState(false)
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const emojiRef = useRef<HTMLDivElement>(null)

  // 点外面关掉表情面板
  useEffect(() => {
    if (!showEmoji) return
    const onDown = (e: MouseEvent) => {
      if (!emojiRef.current?.contains(e.target as Node)) setShowEmoji(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [showEmoji])

  const insertEmoji = (emoji: string) => {
    const el = areaRef.current
    if (!el) {
      setText((t) => t + emoji)
      return
    }
    // 插到光标处而不是无脑追加到末尾——用户常想在句中加表情
    const start = el.selectionStart ?? text.length
    const end = el.selectionEnd ?? text.length
    const next = text.slice(0, start) + emoji + text.slice(end)
    setText(next)
    requestAnimationFrame(() => {
      el.focus()
      el.selectionStart = el.selectionEnd = start + emoji.length
    })
  }

  const uploadImage = async (file: File) => {
    if (uploading) return
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await authFetch(`${API}/uploads`, { method: 'POST', body: form })
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(detail?.detail || '图片上传失败')
      }
      const data = await res.json()
      // 直接作为一条消息发出去；图文混排会让「已发送/未发送」变得难以表达
      await onSend(`![图片](${API}/uploads/${data.id})`)
    } catch (err) {
      onError?.(err instanceof Error ? err.message : '图片上传失败')
    } finally {
      setUploading(false)
    }
  }

  const submit = async () => {
    const t = text.trim()
    if (!t || disabled) return
    setText('')
    await onSend(t)
  }

  return (
    <div className="chat-input">
      {showEmoji && (
        <div className="emoji-panel" ref={emojiRef}>
          {EMOJI_GROUPS.map((g) => (
            <div key={g.label} className="emoji-group">
              <small>{g.label}</small>
              <div className="emoji-grid">
                {g.items.map((e) => (
                  <button key={e} type="button" onClick={() => insertEmoji(e)}>{e}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="chat-input-row">
        <button
          type="button"
          className="chat-input-icon"
          aria-label="表情"
          onClick={() => setShowEmoji((v) => !v)}
        >😊</button>
        <button
          type="button"
          className="chat-input-icon"
          aria-label="发送图片"
          disabled={uploading}
          onClick={() => fileRef.current?.click()}
        >{uploading ? '⏳' : '🖼️'}</button>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) uploadImage(f)
            e.target.value = ''  // 同一张图连传两次也要触发 change
          }}
        />
        <textarea
          ref={areaRef}
          value={text}
          placeholder={placeholder}
          rows={2}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onPaste={(e) => {
            const img = Array.from(e.clipboardData.files).find((f) => f.type.startsWith('image/'))
            if (img) {
              e.preventDefault()   // 截图直接粘贴——报 UI 问题的主要方式
              uploadImage(img)
            }
          }}
          onKeyDown={(e) => {
            if (shouldSubmitComposer({
              key: e.key,
              shiftKey: e.shiftKey,
              isComposing: (e.nativeEvent as KeyboardEvent).isComposing,
            })) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <button className="chat-input-send" onClick={submit} disabled={!text.trim() || disabled}>
          发送
        </button>
      </div>
    </div>
  )
}

/** 消息正文渲染：把 `![](…)` 图片语法渲染成图，其余按纯文本（不解析 Markdown）。 */
export function ChatBody({ content }: { content: string }) {
  const parts = content.split(/(!\[[^\]]*\]\([^)]+\))/g).filter(Boolean)
  return (
    <>
      {parts.map((part, i) => {
        const m = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(part)
        if (!m) return <span key={i}>{part}</span>
        return (
          <a key={i} href={m[2]} target="_blank" rel="noreferrer" className="chat-image-link">
            <img src={m[2]} alt={m[1] || '图片'} loading="lazy" className="chat-image" />
          </a>
        )
      })}
    </>
  )
}
