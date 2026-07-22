# Phase 85: isolated Windows CFU chronology checkpoint

Phase 85 is an input-disabled laboratory checkpoint. It extends the exact
Phase 84 cold-attach sequence through the independently owned Windows CFU
inventory exchange, then stops before Heat processing or Linux input
registration.

## Exact scope

After the Phase 84 device-configuration exchange, the driver:

1. preserves the captured owner-to-owner delay;
2. reads report `0x60` and validates the one declared component against the
   exact installed offer metadata;
3. sends start-transaction and start-list information records;
4. sends the installed 16-byte offer with token `0xa0` and no force flags;
5. validates every immediate report-`0x65` DATA response;
6. sends end-list only when the offer response is the captured
   old-or-same-version rejection;
7. preserves the captured post-CFU delay and reads final report `0x73`;
8. stops at `windows-heat-owner-required` with input disabled.

There is no firmware payload path. If the panel returns accept, busy, skip, an
unknown result, or malformed data, the driver stops at
`windows-cfu-branch-required` and sends no payload.

## Isolation and test order

Phase 84 remains the first hardware gate and is not changed by this work.
Phase 85 must not be armed until Phase 84 has independently reached
`windows-cfu-owner-required` without a transport or protocol error. The saved
GRUB default remains the working Phase 75 baseline.

Phase 86 is a separate opt-in continuation which admits Heat only after this
complete no-update path reaches its final report-`0x73` boundary. It does not
change the Phase 85 checkpoint.

Expected Phase 85 terminal state for the captured installed firmware is:

```text
initialization_stage=windows-heat-owner-required
parity_heat_owner_required=1
mode_enabled=0
```

The early and late report-`0x73` values, report-`0x60` prefix, and complete
offer response are exported in `behavior_stats` for comparison with Windows.
