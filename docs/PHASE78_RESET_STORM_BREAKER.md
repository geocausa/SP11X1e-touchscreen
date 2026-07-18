# Phase 78 reset-storm circuit breaker

Phase 78 is a bounded diagnostic extension to Phase 77. Three panel reset
notifications no more than five seconds apart escalate the third recovery from
software descriptor re-enumeration to the existing full hardware power/reset
path. The streak is cleared only after that hardware path succeeds.

The circuit breaker was exercised on hardware during a reset storm. Software
re-enumeration repeatedly succeeded, the escalation fired as designed, but the
panel later reset again. This proves that a successful re-enumeration or a
single hardware cycle does not by itself remove the storm's underlying cause.
Phase 78 is therefore retained as an opt-in diagnostic and is not the saved
baseline or a claimed fix.

Its counters are `reset_storm_escalations` and `rapid_reset_streak`. The
dedicated `sp11-phase78-storm-breaker` entry is one-shot and preserves all
Phase 75 assets.
