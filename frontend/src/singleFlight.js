export async function runSingleFlight(lockRef, operation) {
  if (lockRef.current) return false
  lockRef.current = true
  try {
    await operation()
    return true
  } finally {
    lockRef.current = false
  }
}
