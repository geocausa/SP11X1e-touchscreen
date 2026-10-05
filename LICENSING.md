# Licensing and provenance

This repository is primarily Linux kernel and kernel-adjacent work.  The
existing top-level `LICENSE` and file-level SPDX identifiers remain in force.
This document clarifies provenance and future contribution policy; it does not
relicense third-party code.

## Existing files

A file's `SPDX-License-Identifier` is authoritative for that file.  Preserve
existing copyright and license notices when copying, modifying, or moving code.

The repository contains both project-authored code and files derived from or
copied from Linux kernel sources during hardware bring-up.  Do not replace
existing SPDX expressions merely to make the tree look uniform.

Files without an explicit file-level license remain subject to the repository's
existing GPL-2.0 licensing policy unless a more specific notice or third-party
license applies.

## geoca contribution grant

To remove ambiguity for downstream and upstream maintainers: to the extent a
change in this repository is an original copyrightable contribution by
**geoca**, it may be reused, modified, redistributed, and submitted upstream
under the license expression that already governs the file or patch in which
that contribution appears.

This applies only to geoca's contributions and does not alter third-party
copyright or license terms.

## Future kernel work

For future changes intended for Linux upstream:

- preserve the existing SPDX expression when modifying an existing kernel
  file;
- put SPDX identifiers at the first possible line, following kernel placement
  rules;
- for a **new, fully original kernel file**, `GPL-2.0 OR BSD-2-Clause` may be
  used when the target subsystem accepts it and no incompatible source material
  was used;
- otherwise use the license expected by the target subsystem, commonly
  `GPL-2.0`;
- use `Linux-syscall-note` only for genuine UAPI files where that exception is
  appropriate.

Linux kernel licensing rules:
https://docs.kernel.org/process/license-rules.html

## Reverse-engineering and vendor material

Hardware behavior may be independently implemented from lawful observations,
public documentation, captures, hashes, and reproducible experiments.  Do not
copy proprietary Microsoft/Qualcomm/vendor source into candidate Linux code.
Do not commit proprietary firmware, DLL/SYS files, or other payloads merely
because they were used as local evidence.

When open-source code is imported or adapted, record the upstream project,
exact revision, source path, and license and preserve the original notices.

## Attribution

Preserve file-level copyright notices, SPDX identifiers, and relevant commit
history.  Where a new project-authored file carries a BSD-2-Clause alternative,
its copyright/license notice supplies the attribution requirement.

## DCO is separate

A repository license or the contribution grant above is not a Linux kernel
`Signed-off-by:`.  Kernel submissions must separately satisfy the Developer's
Certificate of Origin and each signer must provide their own sign-off.

See `CONTRIBUTING.md` and `UPSTREAMING.md`.
