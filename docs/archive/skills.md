# Skills

Long-running skills should check `ctx.cancelled` at safe points and return
`SkillResult(status="cancelled", content=f"cancelled: {ctx.cancellation.reason}")`
when cancellation is requested. The runtime uses this result to record
`SkillCancelled` events and keep agent tool-call history consistent across
reloads and restarts.
