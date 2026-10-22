import { UserProfile } from '@clerk/react'
import { KeyRound } from 'lucide-react'
import { EmptyState, Page } from '../components/ui'
import { useAppAuth } from '../lib/auth'
import { useT } from '../lib/i18n'

/**
 * Account & security (spec FR-41, implementation-plan-v2 D25). Clerk's own screens for changing
 * or setting a password, sign-in methods and active sessions. Passwords never reach HUDA's server.
 */
export default function AccountPage({ admin = false }) {
  const { t } = useT()
  const auth = useAppAuth()
  return (
    <Page title={t('account.title')} intro={t('account.intro')}>
      {auth.mock ? (
        <EmptyState icon={KeyRound} text={t('account.mock')} />
      ) : (
        <div className="[&_.cl-rootBox]:w-full [&_.cl-cardBox]:w-full [&_.cl-cardBox]:max-w-none">
          <UserProfile routing="path" path={admin ? '/admin/account' : '/app/account'} />
        </div>
      )}
    </Page>
  )
}
