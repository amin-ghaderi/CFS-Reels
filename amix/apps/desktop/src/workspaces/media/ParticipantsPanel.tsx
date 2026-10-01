import { useEffect, useState } from "react";

import { createParticipant, listParticipants, renameParticipant } from "../../api/client";
import { asFailure } from "../../api/errors";
import type { Participant, ProjectInfo } from "../../api/types";
import { cleanedParticipantName, PARTICIPANTS_CHANGED_EVENT } from "../../participants/participants";
import { useProjectData } from "../../project/ProjectData";

export function ParticipantsPanel({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const [rows, setRows] = useState<Participant[]>([]);
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    let stop = false;
    void listParticipants(project.handle)
      .then((listed) => {
        if (!stop) {
          setRows(listed);
        }
      })
      .catch((error: unknown) => {
        if (!stop) {
          data.setNotice(asFailure(error));
        }
      });
    return () => {
      stop = true;
    };
  }, [project.handle]);

  async function add() {
    const displayName = cleanedParticipantName(name);
    if (!displayName) {
      data.setNotice({ code: "invalid_participant_name", message: "Enter a participant name." });
      return;
    }
    data.setBusy(true);
    data.setNotice(null);
    try {
      const created = await createParticipant(project.handle, displayName);
      setRows((current) => [...current, created]);
      setName("");
      window.dispatchEvent(new Event(PARTICIPANTS_CHANGED_EVENT));
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  async function rename(participantId: string) {
    const displayName = cleanedParticipantName(draft);
    if (!displayName) {
      data.setNotice({ code: "invalid_participant_name", message: "Enter a participant name." });
      return;
    }
    data.setBusy(true);
    data.setNotice(null);
    try {
      const updated = await renameParticipant(project.handle, participantId, displayName);
      setRows((current) => current.map((row) => (row.participant_id === updated.participant_id ? updated : row)));
      setEditing(null);
      window.dispatchEvent(new Event(PARTICIPANTS_CHANGED_EVENT));
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  return (
    <section className="context" aria-label="Participants">
      <div className="toolbar">
        <h2>Participants</h2>
      </div>
      {rows.length === 0 ? <p className="muted">No participants yet.</p> : null}
      <ul className="asset-list">
        {rows.map((row) => (
          <li key={row.participant_id}>
            {editing === row.participant_id ? (
              <form
                className="stack"
                onSubmit={(event) => {
                  event.preventDefault();
                  void rename(row.participant_id);
                }}
              >
                <input value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Display name" />
                <button type="submit" disabled={data.busy || project.read_only}>Save</button>
              </form>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setEditing(row.participant_id);
                  setDraft(row.display_name);
                }}
                disabled={project.read_only}
              >
                <span>{row.display_name}</span>
              </button>
            )}
          </li>
        ))}
      </ul>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void add();
        }}
      >
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Display name"
          aria-label="New participant"
          disabled={project.read_only}
        />
        <button type="submit" disabled={data.busy || project.read_only}>Add participant</button>
      </form>
    </section>
  );
}
