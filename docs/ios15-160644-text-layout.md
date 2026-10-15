# 160644 text batch layout repair

160643 device regression: the 40-paragraph test response persisted all 4767 characters, while the visible assistant stayed at paragraph 15. The final paragraph occupied only 63pt and did not recover after cached-session reentry. Queue Q160643 subsequently completed normally.

AssistantBlock.content publishes on the block, but ChatMessage does not forward its child notifications. The coordinator observes ChatMessage.objectWillChange and blocks.count; neither reliably updates the layout estimates for in-place text batches. SelfSizingCell may retain its measured height indefinitely, or accept the streaming precalc. Invalidating layout alone does not invalidate those values.

This patch emits a text-block layout signal after each committed batch, including the final attributed-string cache update. The coordinator collects stable item identities and drains them through the existing throttled layout flush. It discards cell/index/precalc/memo heights, refreshes estimates, and reconfigures the changed rows. It does not depend on the assistant being the transcript tail or on isProcessing remaining true.

Verification must distinguish source checks, actual Swift build, and device rendering. Existing source checks do not prove UIKit correctness. Required device acceptance: stream a 40-paragraph answer, queue a second user mid-stream, verify all 40 paragraphs are readable before and after completion/reentry; verify normal queue execution, repeated scrolling, and absence of sustained gaps, overlap or new crashes. The IPA remains unverified on-device until the user installs it. Do not auto-install or restart.
