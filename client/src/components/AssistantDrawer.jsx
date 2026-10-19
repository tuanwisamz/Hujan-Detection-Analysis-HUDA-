import { Send, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { Button, inputClass } from './ui'

const TOOL_LABELS = {
  get_zone_status: 'zone status',
  get_nowcast: 'radar nowcast',
  get_forecast: 'forecast',
  get_official_warnings: 'MET warnings',
  list_recent_alerts: 'recent alerts',
  draft_warning: 'draft warning',
}

/** HUDA Assistant chat (spec FR-22). Answers come only from tools; the trace is shown. */
export default function AssistantDrawer({ open, onClose }) {
  const { t } = useT()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const listRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const send = async (text) => {
    const message = text.trim()
    if (!message || busy) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text: message }])
    setBusy(true)
    try {
      const res = await api('/agent/chat', { method: 'POST', body: { message, conversation_id: conversationId } })
      setConversationId(res.conversation_id)
      setMessages((m) => [...m, { role: 'assistant', text: res.reply, tools: res.tool_calls, pending: res.pending_warning_id }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', text: e.message, error: true }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {open && (
        <section
          role="dialog"
          aria-modal="false"
          aria-label={t('assistant.title')}
          className="fixed inset-x-0 bottom-0 z-[1200] flex h-[75vh] flex-col rounded-t-2xl border border-line bg-surface shadow-2xl lg:inset-x-auto lg:bottom-6 lg:right-6 lg:h-[34rem] lg:w-[24rem] lg:rounded-2xl"
        >
          <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div>
              <h2 className="text-lg font-bold">{t('assistant.title')}</h2>
              <p className="text-sm text-muted">{t('assistant.intro')}</p>
            </div>
            <button type="button" onClick={onClose} className="-mr-2 rounded-lg p-2 text-muted hover:text-ink" aria-label={t('common.close')}>
              <X size={20} aria-hidden="true" />
            </button>
          </header>

          <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
            {messages.length === 0 && (
              <div className="space-y-2">
                {['assistant.suggest1', 'assistant.suggest2', 'assistant.suggest3'].map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => send(t(k))}
                    className="block w-full rounded-lg border border-line px-3 py-2.5 text-left text-sm hover:border-primary hover:bg-paper"
                  >
                    {t(k)}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <p key={i} className="ml-8 rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-white">
                  {m.text}
                </p>
              ) : (
                <div key={i} className="mr-6">
                  <p className={`rounded-2xl rounded-bl-md px-4 py-2.5 ${m.error ? 'bg-level-red-soft' : 'bg-paper'}`}>{m.text}</p>
                  {m.tools?.length > 0 && (
                    <p className="mt-1 px-1 text-xs text-muted">
                      {t('assistant.tools', { tools: [...new Set(m.tools.map((x) => TOOL_LABELS[x.name] || x.name))].join(', ') })}
                    </p>
                  )}
                  {m.pending && <p className="mt-1 px-1 text-xs font-semibold text-primary">{t('assistant.pending')}</p>}
                </div>
              ),
            )}
            {busy && (
              <p className="mr-6 inline-flex gap-1 rounded-2xl bg-paper px-4 py-3" aria-label={t('common.loading')}>
                {[0, 1, 2].map((d) => (
                  <span key={d} className="size-2 animate-bounce rounded-full bg-muted" style={{ animationDelay: `${d * 120}ms` }} />
                ))}
              </p>
            )}
          </div>

          <form
            className="flex gap-2 border-t border-line p-3"
            onSubmit={(e) => {
              e.preventDefault()
              send(input)
            }}
          >
            <label className="sr-only" htmlFor="assistant-input">
              {t('assistant.placeholder')}
            </label>
            <input
              id="assistant-input"
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              maxLength={1000}
              placeholder={t('assistant.placeholder')}
              className={inputClass}
            />
            <Button type="submit" busy={busy} aria-label={t('assistant.send')} className="px-3">
              {!busy && <Send size={18} aria-hidden="true" />}
            </Button>
          </form>
        </section>
      )}
    </>
  )
}
