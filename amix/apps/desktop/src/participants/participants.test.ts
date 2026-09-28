import { describe, expect, it } from "vitest";

import { cleanedParticipantName, participantRows } from "./participants";

describe("participants", () => {
  it("keeps a trimmed display name and rejects a blank one", () => {
    expect(cleanedParticipantName("  Ava  ")).toBe("Ava");
    expect(cleanedParticipantName("   ")).toBeNull();
  });

  it("does not turn the display name into the identity", () => {
    const rows = participantRows([{ participant_id: "11111111-1111-1111-1111-111111111111", display_name: "Ava" }]);
    expect(rows[0].participant_id).not.toBe(rows[0].display_name);
    expect(rows[0].display_name).toBe("Ava");
  });
});
