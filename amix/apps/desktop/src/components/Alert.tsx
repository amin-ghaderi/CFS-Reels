import type { EngineFailure } from "../api/types";

export function Alert({ failure }: { failure: EngineFailure }) {
  return (
    <div className="banner" role="alert">
      <div>{failure.message}</div>
      <details>
        <summary>Details</summary>
        <div>Code: {failure.code}</div>
      </details>
    </div>
  );
}
