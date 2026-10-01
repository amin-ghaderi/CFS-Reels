/** Participant names are display text. The id is assigned by the engine. */

export const PARTICIPANTS_CHANGED_EVENT = "amix-participants-changed";

export function cleanedParticipantName(value: string): string | null {
  const name = value.trim();
  if (!name || name.length > 80) {
    return null;
  }
  return name;
}

export function participantRows(
  rows: { participant_id: string; display_name: string }[],
): { participant_id: string; display_name: string }[] {
  return rows.map((row) => ({ participant_id: row.participant_id, display_name: row.display_name }));
}
