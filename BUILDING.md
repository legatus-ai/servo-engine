# Building servo-engine (Legatus fork)

## Windows (native)

Fresh full builds need, on `PATH` before invoking cargo:

- MSVC 14.44 + Windows SDK (VsDevCmd is broken in this BuildTools SKU;
  set `INCLUDE`/`LIB` by hand — see `msvc-env.ps1` pattern in the
  goal-loop scratch space).
- NASM (`C:\Program Files\NASM`), LLVM (`LIBCLANG_PATH` + `lld-link`).
- Python 3 via the repo `.venv` (`PYTHON3=.../.venv/Scripts/python.exe`).
- **MozillaBuild (moztools) for `mozjs-sys`. NOT installed on this box
  and must NOT be installed without Gary's explicit approval (box is
  heavily loaded). Consequence: only workspaces with a warm target dir
  rebuild on Windows (e.g. the runtime probe); fresh workspaces
  (servo-engine root, servoshell) cannot compile here. Do fresh builds
  in WSL instead.**

## WSL (Ubuntu-24.04): long-batch rules

These are load-bearing. A detached batch does NOT keep the distro
alive: `setsid`/`nohup` children die when Ubuntu idles out, and every
poll then BOOTS the VM, reads a frozen log, and lets it stop again —
manufacturing evidence that everything is fine.

1. Run each chunk FOREGROUND in a single `wsl` invocation, sized to fit
   the tool timeout, so the client holds the distro open by
   construction. If the client timeout kills the run, the chunk was too
   big — split it, do not background it.
2. Never trust log growth. Check the PRODUCER with
   `pgrep -a -f wptrunner` / `pgrep -a -f servoshell` inside the same
   invocation. A frozen log means finished, crashed, or killed — only
   the process table (and `wsl -l -v`) tells which.
3. Heartbeat to a Windows-visible file
   (`/mnt/c/.../wpt-heartbeat.txt`, timestamped lines) so stalled
   (VM up, heartbeat stale) vs dead (VM stopped) are distinguishable
   from outside.
4. `mach test-wpt` SILENTLY SKIPS unknown test paths with exit 0.
   Always verify the executed test count afterwards (parse `test_end`
   in `--log-raw`); a count of zero is a path error, not a pass.
5. `-j 4` for builds; `--processes 4` for wptrunner. Post a tracker-log
   line before any long build so the pane engineer's builds don't
   collide.

## WSL toolchain (one-time)

```sh
sudo apt-get install -y clang libclang-dev llvm m4 nasm cmake \
  libssl-dev python3-venv libfreetype6-dev libfontconfig1-dev \
  libx11-dev libxcb1-dev libxcb-render0-dev libxcb-shape0-dev \
  libxcb-xfixes0-dev libxkbcommon-dev libwayland-dev libegl-dev \
  libgl-dev libasound2-dev libdbus-1-dev libxrandr-dev libxcursor-dev \
  libxi-dev libudev-dev
curl -LsSf https://astral.sh/uv/install.sh | sh   # mach needs `uv`
```

rustup installs the pinned toolchain from `rust-toolchain.toml` on
first use. `./mach` provisions its own venv automatically.
