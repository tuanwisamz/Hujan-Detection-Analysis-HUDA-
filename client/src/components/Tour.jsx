import { useState } from 'react'
import { useT } from '../lib/i18n'
import { Button, Dialog } from './ui'

const KEY = 'huda.tourDone'
const STEPS = [1, 2, 3]

function seen() {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return true
  }
}

/** First-visit tour of the Live map (spec §10.1 Discoverability, §10.2 Learning). */
export default function Tour() {
  const { t } = useT()
  const [step, setStep] = useState(() => (seen() ? 0 : 1))
  const close = () => {
    try {
      localStorage.setItem(KEY, '1')
    } catch {
      /* ignore */
    }
    setStep(0)
  }
  const last = step === STEPS.length
  return (
    <Dialog
      open={step > 0}
      title={step ? t(`tour.${step}.title`) : ''}
      onClose={close}
      footer={
        <>
          <span className="mr-auto self-center text-sm text-muted tabular">
            {step} / {STEPS.length}
          </span>
          <Button onClick={last ? close : () => setStep(step + 1)}>{last ? t('tour.done') : t('tour.next')}</Button>
        </>
      }
    >
      {step > 0 && <p>{t(`tour.${step}.body`)}</p>}
    </Dialog>
  )
}
