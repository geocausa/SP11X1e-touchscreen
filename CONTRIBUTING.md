# Contributing

Contributions are welcome.  The project keeps extensive hardware-validation
history, but changes intended for Linux should be prepared so they can be
reviewed as ordinary upstream kernel patches.

## Rights and provenance

Only contribute material you have the right to submit.  Preserve existing
copyright, attribution, and `SPDX-License-Identifier` lines.

For copied or adapted open-source material, record the upstream project, exact
commit/revision, source path, and license.  Do not commit proprietary firmware,
Windows drivers, DLLs, vendor source, credentials, or other material whose
redistribution rights are unclear.

Read `LICENSING.md` before changing a license header.

## Developer Certificate of Origin

Kernel-bound changes must comply with the Linux Developer's Certificate of
Origin.  Sign commits you are entitled to certify with:

```bash
git commit -s
```

A `Signed-off-by:` line is the signer's own certification.  Never invent or
copy another person's sign-off.  Likewise, use `Co-developed-by:`,
`Reviewed-by:`, `Tested-by:`, `Acked-by:` and similar kernel trailers only when
the named person has actually provided or clearly authorized them under kernel
process rules.

Kernel submission guidance:
https://docs.kernel.org/process/submitting-patches.html

## Kernel-facing changes

For changes destined for Linux:

- recreate the accepted behavior against an appropriate current upstream tree;
- preserve the target file's SPDX expression;
- keep each patch to one logical change;
- separate debug instrumentation and experimental controls from the final
  functional patch;
- prefer existing kernel interfaces and bindings over project-specific APIs;
- update DT bindings/documentation when required;
- run the relevant build/tests and `scripts/checkpatch.pl` before submission.

## Evidence

Tie hardware claims to reproducible observations: logs, captures, hashes,
protocol traces, device identity, or repeatable tests.  Reverse-engineered
behavior should be independently implemented; do not paste decompiled or
proprietary vendor source into kernel patches.

## Historical experiments

Preserve useful experimental history in this repository, but do not require
upstream maintainers to review that history as part of the final patch.  The
upstream submission should contain the smallest change needed to reproduce the
validated result.
