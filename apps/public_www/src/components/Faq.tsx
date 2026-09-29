import type { FaqItem } from '../lib/content'

export function Faq({ items }: { items: FaqItem[] }) {
  return (
    <section className="section fold faq" aria-labelledby="faq-heading">
      <div className="container">
        <h2 id="faq-heading">FAQ</h2>
        {items.map((item) => (
          <details key={item.q}>
            <summary>{item.q}</summary>
            <p>{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  )
}
