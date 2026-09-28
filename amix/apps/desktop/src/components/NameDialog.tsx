import { useEffect, useId, useRef, useState } from "react";

export function NameDialog({
  parent,
  busy,
  onCancel,
  onSubmit,
}: {
  parent: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const errorId = useId();
  const blank = name.trim().length === 0;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || dialog.open) {
      return;
    }
    dialog.showModal();
    inputRef.current?.focus();
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="card dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (blank) {
            setError("Enter a project name.");
            inputRef.current?.focus();
            return;
          }
          setError("");
          onSubmit(name);
        }}
      >
        <h2 id={titleId}>Name the project</h2>
        <p className="muted">{parent}</p>
        <label htmlFor="project-name">Project name</label>
        <input
          ref={inputRef}
          id="project-name"
          name="project-name"
          type="text"
          value={name}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => {
            setName(event.target.value);
            if (error) {
              setError("");
            }
          }}
        />
        {error ? (
          <p id={errorId} className="field-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="actions">
          <button className="primary" type="submit" disabled={busy}>
            Create
          </button>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </dialog>
  );
}
