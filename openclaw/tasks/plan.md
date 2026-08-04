# Implementation Plan: Five-device Fanqie Closed Loop

## Overview

Complete the five requested tasks in dependency order: repair the NOVEL-02 mapping, verify multi-device dispatch, automate first-run setup, add a long-running scanner service, and run a bounded stability soak.

## Architecture Decisions

- Treat the Fanqie chapter list as the publishing source of truth; Feishu is reconciled only after device verification.
- Serialize work per device while allowing different devices to run independently.
- Make first-run onboarding and work creation idempotent so retries resume instead of duplicating books or chapters.
- Use a bounded soak test in this session; retain a reusable command for a longer 24-hour run.

## Task List

### Phase 1: Repair mapping

- [ ] Rename or safely bind the existing 54481 work to NOVEL-02.
- [ ] Publish and verify CH-002, then reconcile the stale Feishu success state.

### Phase 2: Multi-device acceptance

- [ ] Inspect all five devices and run idempotent dispatch checks.
- [ ] Verify no duplicate chapters and safe terminal pages.

### Phase 3: First-run automation

- [ ] Add tests for onboarding dismissal and idempotent work creation.
- [ ] Implement and verify the first-run flow.

### Phase 4: Long-running service

- [ ] Add a configurable scanner loop with health logs and graceful shutdown.
- [ ] Test serialization, retries, and device quarantine behavior.

### Phase 5: Stability

- [ ] Run a bounded multi-cycle soak across all five devices.
- [ ] Record results and provide the longer-run command.

## Checkpoints

- Phase 1: NOVEL-02 device title, chapter list, draft box, and Feishu agree.
- Phases 2-4: full tests, lint, and type checks pass.
- Phase 5: repeated cycles produce no duplicate publication or unsafe device state.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Platform review latency | Medium | Accept `审核中` as submitted, then reconcile later. |
| New-account onboarding overlays | High | Detect semantic labels and dismiss idempotently. |
| Stale Feishu success records | High | Never skip based on Feishu alone; verify the target chapter on-device. |
| ADB port rotation | Medium | Read device IDs from the account table and reconnect automatically. |

## Open Questions

- None blocking; the user approved executing tasks 1 through 5 sequentially.
