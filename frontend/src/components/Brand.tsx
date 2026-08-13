export function BrandIcon({ size = 18, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden
    >
      <circle cx="10.5" cy="33.5" r="3.5" fill="currentColor" />
      <path
        d="M14.2 32.7c4.3-8 9.2 1.8 14.3-7 2.7-4.7 5.5-6.7 9-7.3"
        stroke="currentColor"
        strokeWidth="3.6"
        strokeLinecap="round"
      />
      <path
        d="m31.7 13.8 7.8 3.6-5.4 6.8"
        stroke="currentColor"
        strokeWidth="3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="10.5" cy="33.5" r="6.3" stroke="currentColor" strokeOpacity=".3" strokeWidth="1.7" />
    </svg>
  )
}

export function BrandWordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`wordmark ${className}`.trim()}>
      <span className="brand-number">17</span><span className="brand-cn">同游</span>
    </span>
  )
}
