# Voice Trace Motion Specification

`Voice Trace / 문체 흔적` connects four corpus features to a voice-applied sentence.

State contract: `idle or complete → running → complete`. Replay removes previous complete state before running. Completion uses the final human-review animation's `animationend`.

Source blocks and final output geometry remain fixed. Only evidence threads, emphasis marks and the review indicator animate. Computed final end is read by the browser validator: `560ms delay + 120ms duration = 680ms`. Reduced motion immediately shows the complete mapping and sets state to complete.