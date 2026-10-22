import { Siren } from 'lucide-react'
import { useState } from 'react'
import { useApiMutation, useSirenActivations } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { formatDateTime } from '../lib/time'
import { describeRule } from '../lib/rules'
import { Button, ConfirmDialog, useToast } from './ui'

const INVALIDATE = ['sirens', 'sirenActivations', 'automation', 'live']

/** Pending siren approvals (spec FR-35). Shown on Warnings and Sirens. Renders nothing when empty. */
export default function SirenApprovals() {
  const { t, lang } = useT()
  const toast = useToast()
  const pending = useSirenActivations('pending_approval')
  const [confirm, setConfirm] = useState(null)
  const approve = useApiMutation((id) => api(`/admin/siren-activations/${id}/approve`, { method: 'POST' }), INVALIDATE)
  const cancel = useApiMutation((id) => api(`/admin/siren-activations/${id}/cancel`, { method: 'POST' }), INVALIDATE)
  const items = pending.data?.items || []
  if (!items.length) return null
  const done = (msg) => ({ onSuccess: () => (toast(msg), setConfirm(null)), onError: (e) => (toast(e.message, 'error'), setConfirm(null)) })

  return (
    <section aria-label={t('sirens.pendingTitle')} className="mb-4 space-y-2">
      {items.map((a) => (
        <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-xl border-2 border-level-red bg-level-red-soft p-4">
          <Siren size={24} aria-hidden="true" className="shrink-0 text-level-red" />
          <div className="min-w-0 flex-1">
            <p className="font-bold">{t('sirens.pendingHeadline', { siren: a.siren_name, zone: a.zone_name })}</p>
            <p className="text-sm">
              {a.rule ? describeRule(a.rule, t) : a.reason} · {formatDateTime(a.created_at, lang)}
            </p>
          </div>
          <Button variant="danger" onClick={() => setConfirm({ kind: 'approve', a })}>
            {t('sirens.approve')}
          </Button>
          <Button variant="secondary" onClick={() => setConfirm({ kind: 'cancel', a })}>
            {t('sirens.cancel')}
          </Button>
        </div>
      ))}
      <ConfirmDialog
        open={confirm?.kind === 'approve'}
        danger
        title={t('sirens.approve')}
        body={t('sirens.confirmApprove', { siren: confirm?.a.siren_name, zone: confirm?.a.zone_name })}
        confirmLabel={t('sirens.approve')}
        busy={approve.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={() => approve.mutate(confirm.a.id, done(t('sirens.sounding')))}
      />
      <ConfirmDialog
        open={confirm?.kind === 'cancel'}
        title={t('sirens.cancel')}
        body={t('sirens.confirmCancel')}
        confirmLabel={t('sirens.cancel')}
        busy={cancel.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={() => cancel.mutate(confirm.a.id, done(t('sirens.cancelled')))}
      />
    </section>
  )
}
