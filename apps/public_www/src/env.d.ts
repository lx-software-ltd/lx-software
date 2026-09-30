/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MEDIA_BASE_URL?: string
  readonly VITE_CONTACT_TEL?: string
  readonly VITE_CONTACT_WHATSAPP?: string
  readonly VITE_CONTACT_EMAIL?: string
  readonly VITE_CONTACT_WECHAT_ID?: string
  readonly VITE_CONTACT_LINKEDIN?: string
  readonly VITE_GTM_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
