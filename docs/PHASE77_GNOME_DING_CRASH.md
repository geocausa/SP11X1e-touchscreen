# Phase 77 GNOME/DING crash separation

## Result

The July 18 GNOME failure was a userspace desktop-icons failure, not evidence
of a touchscreen transport, Heat parser, or panel-reset fault.

The corrected Phase 77 boot was switched from Plasma Wayland to Ubuntu GNOME
Wayland without rebooting. Under GNOME the same loaded module reached at least
9,533 Heat frames with zero Heat errors, panel resets, recovery failures, or
readiness failures. It later remained clean beyond 10,846 Heat frames while
DING was disabled.

## Crash evidence

Apport retained two temporally adjacent crash reports:

- at 19:11:35, `/usr/bin/gjs-console` crashed with `SIGSEGV` while running
  `/usr/share/gnome-shell/extensions/ding@rastersoft.com/app/ding.js`;
- at 19:14:49, `/usr/bin/gnome-shell --mode=ubuntu` crashed with `SIGSEGV`.

The DING core's faulting native stack was:

```text
gdk_window_get_display
gdk_event_free
GJS boxed-object finalization
SpiderMonkey garbage collection
```

The installed DING files differed from the exact Ubuntu package only by the
locally added touch long-press implementation. That implementation retained
`event.copy()` objects for an idle callback and then called `event.free()`
manually on completion or cancellation. GJS also owns and finalizes those
boxed copies, making the explicit frees a double-free candidate matching the
core exactly.

The later GNOME Shell core faulted inside Mutter's Wayland dispatch and service
channel region. DING is a separate GJS Wayland client using that desktop
service path. The three-minute ordering supports a userspace crash chain, but
does not by itself prove the DING exit was the sole cause of the Mutter fault.

## Remediation

At the operator's request, DING was removed from the active desktop rather
than repaired:

- `ding@rastersoft.com` is in GNOME Shell's disabled-extension list;
- no DING helper process remains;
- the user extension copy was moved outside GNOME's extension path;
- the three modified system files were restored from the exact installed
  `gnome-shell-ubuntu-extensions 50.26.04.7ubuntu` package; and
- `dpkg -V gnome-shell-ubuntu-extensions` reports no modified package files.

The inactive backup is retained under
`/home/geoca/.cache/ding-removed-20260718`. Ubuntu Dock, AppIndicators, tiling,
and the other bundled extensions remain installed and enabled.

One current GNOME log warning names `Microsoft Surface 045E:09AF Touchpad`
and libinput's jump filter. That is the separate type-cover touchpad on
`event5`, not the `Microsoft Surface G6 Touch` touchscreen on `event1`.
