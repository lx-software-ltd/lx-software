import { wechatId } from '../lib/contact'
import { defaultSiteContent } from '../lib/content'
import { usePageMeta } from '../lib/seo'

export function WeChatPage() {
  const id = wechatId()
  const siteName = defaultSiteContent.site.name
  usePageMeta(`WeChat — ${siteName}`, '/wechat', `WeChat QR code for ${siteName}.`)

  return (
    <article className="section legal container">
      <h1>WeChat</h1>
      {id ? <p>WeChat ID: {id}</p> : null}
      <img className="wechat-qr" src="/wechat-qr.png" alt="WeChat QR code" width={728} height={728} />
    </article>
  )
}
