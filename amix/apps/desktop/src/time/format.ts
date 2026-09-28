/** Display only. Canonical media time stays integer microseconds. */

export function formatMicroseconds(microseconds: number): string {
  if (!Number.isInteger(microseconds) || microseconds < 0) {
    return "00:00:00.000";
  }
  const totalMillis = Math.floor(microseconds / 1000);
  const millis = totalMillis % 1000;
  const totalSeconds = Math.floor(totalMillis / 1000);
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  return `${pad(hours, 2)}:${pad(minutes, 2)}:${pad(seconds, 2)}.${pad(millis, 3)}`;
}

function pad(value: number, width: number): string {
  return String(value).padStart(width, "0");
}
