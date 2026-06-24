// Placeholder for the Tracking sub-tabs not built yet (Market / Industry / Contracts).
export default function ComingSoon({ title }) {
  return (
    <div className="empty-state" style={{ padding: '64px 20px', textAlign: 'center' }}>
      <div style={{ fontSize: 15, color: 'var(--text-bright)', marginBottom: 6 }}>{title} tracking</div>
      <div style={{ fontSize: 13, color: 'var(--text)' }}>Coming soon.</div>
    </div>
  )
}
