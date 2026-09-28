# CFS specialist roles

Files in `roles/` are persistent specialist operating instructions for AI-assisted tasks.

They describe how an agent should think and decide while doing a named job. They are not pipeline code, not renderer settings, and not a substitute for the project's frozen technical constraints.

## Rule

Whenever a task names a role, the agent must:

1. Read the complete corresponding Markdown file first.
2. Adopt that specialist perspective for the entire task.
3. Follow the project's existing technical constraints.
4. Never let the role override explicit task-specific instructions.
5. Report if the role conflicts with available data instead of guessing.

A role changes judgment. It does not authorize changes to Reels, renderers, framing profiles, transcripts, speaker attribution, or outputs unless the task itself asks for those changes.

## Example invocation

First read and adopt `roles/virtual_director.md`.
Then create the Virtual Director shot plan for CFS03_R02.

## Status

ROLE ARCHITECTURE CREATED — SPECIALIST DEFINITIONS WILL BE EXPANDED INDIVIDUALLY.

## Roles

| File | Area of responsibility |
|---|---|
| `roles/editorial_core.md` | Shared editorial judgment for the show |
| `roles/senior_show_editor.md` | Overall episode shape, pacing, and fidelity |
| `roles/conversation_editor.md` | Long-form conversation arcs for later Reel synthesis |
| `roles/reel_editor.md` | One Reel's selection, order, and length |
| `roles/virtual_director.md` | Multi-camera shot choice for a fixed three-person source |
| `roles/speaker_resolver.md` | Who is speaking, and when. Does not direct cameras |
| `roles/episode_summary_editor.md` | Source-faithful episode summary |
| `roles/visual_hook_director.md` | Optional visual-hook treatment on an already chosen shot |
| `roles/transcript_qa.md` | Transcript text and timestamp checks |
| `roles/framing_supervisor.md` | Locked tiles and framing profiles |
