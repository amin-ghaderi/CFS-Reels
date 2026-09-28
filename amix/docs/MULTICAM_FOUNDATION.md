# Multicam foundation

A shot plan is a third analysis. It reads turns, overlap, layout, and protected regions. Those inputs stay separate.

```
Source media + layout + visual/audio evidence → Overlap
Transcript + diarization + mapping → Turns
Turns + Overlap + Layout + Protected regions → ShotPlan
```

Correcting a speaker does not rerun overlap. Changing the layout does mark overlap stale, because the crops changed. The plan is stale when the active turns, the active overlap, the layout fingerprint, or the protected-region fingerprint no longer match the run that produced it. Phase 11 does not rebuild a stale plan on its own. The workspace says the plan is out of date and leaves the rebuild to the user.

## Planning

The job `build_multicam_plan` calls the existing `plan_shots` function. It does not contain another director. Reaction inserts from the older offline scripts are not called and are not compared with this plan.

The requested range must be covered by both the active turn run and the active overlap run. For this version that range is the overlap window, and the turn window must cover it. A span that neither run measured is not filled in.

`FULL` is used only when that participant has one layout region covering the whole floor interval. Otherwise the shot stays `UNTOUCHED_WIDE` with reason `unbound`. The planner does not pick a different crop.

Protected regions are their own input. They are applied last and override overlap and full shots. They are not stored as overlap or as speaker data.

## Provenance

The plan is one immutable AnalysisRun of kind `shot_plan`. It depends on the exact turn run and the exact overlap run. The config records the layout fingerprint, the protected-region fingerprint, the plan range, and `amix.multicam.plan.v1`. After the rows are committed, the active shot plan switches. A failure leaves the previous plan active. Older plans stay stored.

## Workspace

Multicam is a review workspace. It shows the proxy through the existing player, the overlap regions, and the automatic shots. A region or a shot seeks that same player to the canonical start. The highlighted shot is the one whose half-open range contains the playhead. That lookup is local.

Shot labels are `Full — <participant>`, `Wide`, and `Protected`. The current shot is named the same way beside the picture. The picture itself stays the untouched proxy frame. There is no crop preview, no rendered program, and no manual camera override. Those need a renderer and an authority rule for edits, which are later phases.
