import { wechatId } from '../lib/contact'
import { usePageMeta } from '../lib/seo'

export function WeChatPage() {
  const id = wechatId()
  usePageMeta(
    'WeChat — LX Software',
    '/wechat',
    'WeChat contact for LX Software. The QR code is a placeholder until it is published.',
  )

  return (
    <article className="section legal container">
      <h1>WeChat</h1>
      <p>
        {id
          ? `WeChat ID: ${id}`
          : 'The WeChat ID is not configured yet. It is supplied at build time and is not stored in the repository.'}
      </p>
      <pre className="ascii" aria-hidden="true">
        {['+------------------+', '|                  |', '|   QR  pending    |', '|                  |', '+------------------+'].join('\n')}
      </pre>
      <p>A scannable QR code will replace this block when it is ready. On a phone with WeChat installed, the contact icon opens a chat when an ID is configured.</p>
    </article>
  )
}
