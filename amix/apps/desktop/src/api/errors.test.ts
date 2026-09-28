import { describe, expect, it } from "vitest";

import { mapEngineFailure, jobProblemMessage } from "./errors";

describe("mapEngineFailure", () => {
  it("maps stable engine codes to plain sentences", () => {
    const failure = mapEngineFailure(
      409,
      JSON.stringify({ error: { code: "project_already_locked", message: "ProjectAlreadyLocked: traceback" } }),
    );
    expect(failure.code).toBe("project_already_locked");
    expect(failure.message).toBe("This project is open in another AMIX window.");
    expect(failure.message).not.toContain("traceback");
  });

  it("hides unknown payloads", () => {
    const failure = mapEngineFailure(500, "not-json");
    expect(failure.message).toBe("The engine could not complete that action.");
    expect(failure.code).toBe("http_500");
  });
});

describe("jobProblemMessage", () => {
  it("does not surface raw engine exception text", () => {
    const message = jobProblemMessage("handler_failed");
    expect(message).toBe("The job did not finish.");
    expect(message).not.toContain("Traceback");
    expect(jobProblemMessage(null)).toBe("The job did not finish.");
    expect(jobProblemMessage("media_tool_missing")).toBe("FFmpeg tools are not available.");
    expect(jobProblemMessage("media_tool_missing")).not.toContain("FileNotFoundError");
  });
});
