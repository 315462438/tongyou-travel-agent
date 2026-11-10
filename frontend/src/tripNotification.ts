export type TripNotificationTarget = {
  tripId: string
  kind: 'poll' | 'chat' | 'trip'
  day: number | null
  pollId: string | null
  requestId: number
}

const text = (value: unknown) => typeof value === 'string' ? value.trim() : ''
const validDay = (value: unknown, days: number) => typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= days

export function tripNotificationTarget(item: {type: string; target_kind: string; target_id?: string; meta?: {trip_id?: unknown; poll_id?: unknown; day?: unknown}}, requestId: number): TripNotificationTarget | null {
  if (item.target_kind !== 'trip') return null
  const tripId = text(item.meta?.trip_id) || text(item.target_id)
  if (!tripId) return null
  return {tripId, requestId, kind: item.type === 'trip_poll' ? 'poll' : item.type === 'trip_chat' ? 'chat' : 'trip',
    day: validDay(item.meta?.day, Number.MAX_SAFE_INTEGER) ? item.meta!.day as number : null,
    pollId: text(item.meta?.poll_id) || null}
}

/** A notification can outlive edits to a trip; the current poll is authoritative. */
export function resolvePollNotification(target: Pick<TripNotificationTarget, 'day' | 'pollId'>, days: number, polls: {id: string; day?: number | null}[], currentDay = 1) {
  const poll = polls.find(p => p.id === target.pollId)
  const requested = poll ? poll.day : target.day
  const day = validDay(requested, days) ? requested as number : validDay(currentDay, days) ? currentDay : 1
  return {day, pollId: poll && (poll.day == null || poll.day === day) ? poll.id : null}
}
