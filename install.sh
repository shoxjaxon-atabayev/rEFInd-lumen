#!/usr/bin/env bash
# Lumen — installer for a minimal rEFInd boot theme with colour variants.
#
# Two separate steps — generate, then install:
#
#   ./install.sh                    pick colours to generate (no install yet)
#   ./install.sh --color blue       install `blue` now (generates it first if
#                                   it isn't already sitting in build/colors/)
#   ./install.sh --background light  put it on a near-white background instead
#   ./install.sh --list             list the available colours and backgrounds
#   ./install.sh --dry-run          print the plan, change nothing
#   ./install.sh --yes              skip the confirmation prompt
#   ./install.sh --refind-dir PATH  skip detection; PATH is the dir with refind.conf
#   ./install.sh --deploy-refind    run the system's `refind-install` first if
#                                   rEFInd isn't on the ESP yet
#   ./install.sh --uninstall        remove the theme, revert refind.conf
#
# There is no pre-generated colour library shipped in this repo. Run with no
# --color and a terminal attached and you get an interactive multi-select
# menu (arrows to move, Space to toggle, Enter to confirm) — the colours you
# pick are generated locally with tools/generate.py (needs Python 3 + Pillow
# + numpy — this script checks for them first) into build/colors/, which
# persists in this checkout between runs. That step never touches rEFInd.
#
# To actually install one, run `./install.sh --color <name>` — if it's
# already in build/colors/ from the step above this skips straight to
# installing it (no regenerating what you already have); if not, it
# generates just that one colour first. Installing always fully replaces
# whatever colour was there before — no backup is kept, so the ESP doesn't
# accumulate old copies.
#
# Re-runnable and idempotent. It only ever touches:
#   <refind-dir>/themes/lumen/     — the theme payload
#   one marked block inside <refind-dir>/refind.conf
# It never edits EFI boot entries, NVRAM, or Secure Boot, and never touches any
# other bootloader — unless you pass --deploy-refind, which shells out to the
# system's own `refind-install` exactly once.
#
# Needs root to write the ESP; if you don't run it as root it re-execs itself
# with sudo. The generate-only step (no --color) never needs root at all.

set -euo pipefail

if [ -z "${BASH_VERSINFO:-}" ] || [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
  echo "this installer needs bash 4+ (you have ${BASH_VERSION:-a non-bash shell}). Run: bash $0" >&2
  exit 1
fi

ORIG_ARGS=("$@")
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

THEME_SUBDIR="themes/lumen"                   # must match the paths inside theme.conf
INCLUDE_LINE="include ${THEME_SUBDIR}/theme.conf"
MARKER_BEGIN="# BEGIN Lumen (managed by install.sh — do not edit this block by hand)"
MARKER_END="# END Lumen"
DEFAULT_COLOR="white"
DEFAULT_BG="dark"

# COLOR is the single colour to INSTALL (drives look_dir()/theme.conf).
# COLOR_LIST is only used by the generate-only (interactive menu) path — the
# set of colours to generate, no "active" one among them since nothing gets
# installed there. RAW_COLOR_ARGS collects --color tokens as given, before
# validation.
COLOR="$DEFAULT_COLOR"
declare -a RAW_COLOR_ARGS=()
declare -a COLOR_LIST=()
RESOLVED_COLOR_ARG=""
AVAILABLE_COLORS_CACHE=""
# Persistent local cache of generated looks — lives in this checkout, is
# never deleted by this script, and is gitignored (never committed). Both
# the generate-only step and --color install read/write here, so a colour
# generated once is never regenerated on a later --color run.
GENERATED_DIR="$SCRIPT_DIR/build/colors"
BG="$DEFAULT_BG"
REFIND_DIR_OVERRIDE=""
DRY_RUN=0
ASSUME_YES=0
UNINSTALL=0
DEPLOY_REFIND=0
LIST=0

# --------------------------------------------------------------- output --

if [ -t 1 ]; then
  _r=$'\033[31m'; _g=$'\033[32m'; _y=$'\033[33m'; _b=$'\033[1m'; _x=$'\033[0m'
else
  _r=""; _g=""; _y=""; _b=""; _x=""
fi
info() { printf '  %s\n' "$*"; }
step() { printf '\n%s%s%s\n' "$_b" "$*" "$_x"; }
ok()   { printf '%s[ok]%s %s\n'   "$_g" "$_x" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$_y" "$_x" "$*"; }
# die = a deliberate, already-explained stop: clear the trap so we don't also
# print the generic "aborted" line after our specific message.
die()  { printf '%s[error]%s %s\n' "$_r" "$_x" "$*" >&2; trap - EXIT; exit 1; }

on_exit() {
  local status=$?
  [ "$status" -ne 0 ] && printf '%s[error]%s aborted (exit %s) — nothing was left half-written; safe to re-run.\n' "$_r" "$_x" "$status" >&2
  return 0
}
trap on_exit EXIT

# -------------------------------------------------------------- helpers --

# Print the leading comment block (everything from line 2 up to the first
# non-comment line), with the "# " stripped.
usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$SELF"; }

timestamp() { date +%Y%m%d-%H%M%S; }

# A path that definitely doesn't exist yet (two runs in one second, etc.).
unique_path() {
  local base cand n=2
  base="$1-$(timestamp)"
  cand="$base"
  while [ -e "$cand" ]; do cand="${base}-${n}"; n=$((n + 1)); done
  printf '%s\n' "$cand"
}

# Normalise "Obsidian Purple" / obsidian_purple / OBSIDIAN-PURPLE -> obsidian-purple
normalise_color() {
  printf '%s\n' "$1" | tr '[:upper:] _' '[:lower:]--'
}

# dark|light, tolerant of black/white/… synonyms
normalise_bg() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    light | white | l) echo light ;;
    dark  | black | d | "") echo dark ;;
    *) echo "$1" ;;
  esac
}

GENERATE_PY="$SCRIPT_DIR/tools/generate.py"

# Canonical colour names, in the generator's own order — cached after the
# first call since it shells out to python3.
available_colors() {
  if [ -z "$AVAILABLE_COLORS_CACHE" ]; then
    AVAILABLE_COLORS_CACHE="$(python3 "$GENERATE_PY" --list)" \
      || die "'python3 $GENERATE_PY --list' failed — check your Python/Pillow/numpy install."
  fi
  printf '%s\n' "$AVAILABLE_COLORS_CACHE"
}

# "obsidian-purple" -> "Obsidian Purple"
display_name() {
  local word out=""
  for word in ${1//-/ }; do
    out="$out${out:+ }${word^}"
  done
  printf '%s\n' "$out"
}

check_dependencies() {
  step "checking dependencies"
  command -v python3 >/dev/null 2>&1 \
    || die "python3 not found — install Python 3 (e.g. pacman -S python)."
  python3 -c "import PIL" >/dev/null 2>&1 \
    || die "Python module 'Pillow' not found — install it: pip install Pillow  (or: pacman -S python-pillow)"
  python3 -c "import numpy" >/dev/null 2>&1 \
    || die "Python module 'numpy' not found — install it: pip install numpy  (or: pacman -S python-numpy)"
  ok "python3 + Pillow + numpy available"
}

unknown_color_warning() {
  printf '%s⚠ Unknown color:%s %s\n' "$_y" "$_x" "$1" >&2
  printf '  Available colors: %s\n' "$(available_colors | tr '\n' ' ')" >&2
}

# Split "$1" on commas, normalise each token, append non-empty ones to
# RAW_COLOR_ARGS. Handles both --color a,b and repeated --color a --color b.
add_color_arg() {
  local raw="$1" tok toks
  IFS=',' read -ra toks <<< "$raw"
  for tok in "${toks[@]}"; do
    tok="$(normalise_color "$tok")"
    [ -n "$tok" ] && RAW_COLOR_ARGS+=("$tok")
  done
}

# The dir holding selection_big/small.png + icons/ for the chosen colour+bg,
# inside the persistent GENERATED_DIR cache.
look_dir() {
  if [ "$BG" = "light" ]; then
    printf '%s\n' "$GENERATED_DIR/$COLOR/light"
  else
    printf '%s\n' "$GENERATED_DIR/$COLOR"
  fi
}

bg_image() { printf '%s\n' "$SCRIPT_DIR/backgrounds/$BG.png"; }

# True if GENERATED_DIR/<colour> already holds a complete look (both
# backgrounds) — lets ensure_generated() skip a colour that's already
# sitting on disk from an earlier run instead of needlessly rebuilding it.
is_cached() {
  local d="$GENERATED_DIR/$1"
  [ -f "$d/selection_big.png" ] && [ -f "$d/selection_small.png" ] \
    && ls "$d"/icons/*.png >/dev/null 2>&1 \
    && [ -f "$d/light/selection_big.png" ] && [ -f "$d/light/selection_small.png" ] \
    && ls "$d/light/icons"/*.png >/dev/null 2>&1
}

# Generate every given colour that isn't already cached in GENERATED_DIR.
# Colours already there are left completely untouched.
ensure_generated() {
  local c missing=()
  for c in "$@"; do
    is_cached "$c" || missing+=("$c")
  done
  if [ "${#missing[@]}" -eq 0 ]; then
    info "already generated: $(
      IFS=', '
      echo "$*"
    )"
    return 0
  fi
  info "generating: $(
    IFS=', '
    echo "${missing[*]}"
  )"
  python3 "$GENERATE_PY" "${missing[@]}" --out-dir="$GENERATED_DIR" \
    || die "tools/generate.py failed — see output above."
}

color_note() {
  case "$1" in
    white)           echo "the default — plain white / dark ink" ;;
    green|red|pink|blue)
                     echo "flat $1" ;;
    obsidian-purple) echo "premium · iridescent violet→magenta→teal" ;;
    champagne-gold)  echo "premium · iridescent warm gold foil" ;;
    aurora)          echo "premium gradient · emerald → cyan" ;;
    cyberpunk)       echo "premium gradient · magenta → cyan" ;;
    platinum)        echo "premium gradient · blue-violet steel" ;;
    *)               echo "" ;;
  esac
}

reexec_with_sudo() {
  command -v sudo >/dev/null 2>&1 \
    || die "need root to work with the ESP, and sudo isn't installed — re-run this as root."
  info "$1"
  trap - EXIT
  # Re-run with the already-resolved colour selection appended, so a re-exec
  # (mid-flow, e.g. from ensure_writable) never re-prompts an interactive menu
  # or re-parses an ambiguous --color; last --color on the line wins.
  local args=(${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"})
  [ -n "$RESOLVED_COLOR_ARG" ] && args+=("$RESOLVED_COLOR_ARG")
  exec sudo -- "$SELF" ${args[@]+"${args[@]}"}
}

# Re-exec with sudo up front only if we can't even *look* for rEFInd unprivileged
# (the ESP is very often root-only, mode 700). If detection is possible as the
# user, we defer the decision to ensure_writable() once the real target is known.
escalate_if_needed() {
  [ "$DRY_RUN" -eq 1 ] && return 0
  [ "$(id -u)" -eq 0 ] && return 0

  if [ -n "$REFIND_DIR_OVERRIDE" ]; then
    { [ -d "$REFIND_DIR_OVERRIDE" ] && [ -w "$REFIND_DIR_OVERRIDE" ]; } && return 0
    reexec_with_sudo "not root — re-running under sudo to write $REFIND_DIR_OVERRIDE…"
  fi

  local r
  for r in /boot /boot/efi /boot/EFI /efi; do
    [ -e "$r" ] || continue
    ls "$r" >/dev/null 2>&1 || \
      reexec_with_sudo "not root and $r is not readable — re-running under sudo…"
  done
}

# Definitive check: we know the rEFInd dir now; if we can't write it, escalate.
ensure_writable() {
  [ "$(id -u)" -eq 0 ] && return 0
  [ -w "$1" ] && return 0
  reexec_with_sudo "not root — re-running under sudo to write $1…"
}

# ---------------------------------------------------------- colour picker --

# Interactive multi-select menu over a real TTY: ↑/↓ move, Space toggles,
# Enter confirms. Sets COLOR_LIST. Falls back to DEFAULT_COLOR if nothing
# ends up checked.
interactive_color_menu() {
  local -a names=() checked=()
  local n i idx=0 total key rest

  while IFS= read -r n; do
    names+=("$n")
    if [ "$n" = "$DEFAULT_COLOR" ]; then checked+=(1); else checked+=(0); fi
  done < <(available_colors)
  total=${#names[@]}

  printf '\n%sLumen%s\n' "$_b" "$_x"
  printf '─────────────\n\n'
  printf 'Select theme colours:\n\n'

  # menu_lines is every line draw_menu prints in one pass (colour rows + a
  # blank separator + the hint line) — the cursor-up amount on a redraw MUST
  # match this exactly, or each redraw lands a couple of rows short and
  # leaves stale duplicate rows behind (the hint line used to be printed
  # once, outside this function, so the up-count never accounted for it).
  local drawn=0 menu_lines=$((total + 2))
  draw_menu() {
    [ "$drawn" -eq 1 ] && printf '\033[%dA' "$menu_lines"
    drawn=1
    local j mark cursor note label
    for ((j = 0; j < total; j++)); do
      if [ "${checked[$j]}" -eq 1 ]; then mark="${_g}◉${_x}"; else mark="◯"; fi
      if [ "$j" -eq "$idx" ]; then cursor="${_b}❯${_x}"; else cursor=" "; fi
      label="$(display_name "${names[$j]}")"
      note="$(color_note "${names[$j]}")"
      printf '\033[2K%s %s %-18s %s\n' "$cursor" "$mark" "$label" "$note"
    done
    printf '\033[2K\n\033[2K%s↑/↓%s Navigate   %sSpace%s Select   %sEnter%s Install\n' \
      "$_b" "$_x" "$_b" "$_x" "$_b" "$_x"
  }

  local old_stty
  old_stty="$(stty -g)"
  restore_tty() { stty "$old_stty" 2>/dev/null || true; printf '\033[?25h' >&2; }
  trap 'restore_tty; die "aborted."' INT TERM
  stty -echo -icanon time 0 min 0
  printf '\033[?25l'

  draw_menu

  while true; do
    key=""
    IFS= read -rsn1 key || true
    case "$key" in
      $'\x1b')
        rest=""
        IFS= read -rsn2 -t 0.05 rest || true
        case "$rest" in
          '[A') idx=$(((idx - 1 + total) % total)) ;;
          '[B') idx=$(((idx + 1) % total)) ;;
        esac
        ;;
      ' ') checked[$idx]=$((1 - checked[$idx])) ;;
      '' | $'\n' | $'\r') break ;;
      q | Q) restore_tty; die "aborted." ;;
    esac
    draw_menu
  done

  restore_tty
  trap - INT TERM
  printf '\n'

  COLOR_LIST=()
  for ((i = 0; i < total; i++)); do
    [ "${checked[$i]}" -eq 1 ] && COLOR_LIST+=("${names[$i]}")
  done
  if [ "${#COLOR_LIST[@]}" -eq 0 ]; then
    warn "no colours selected — falling back to default: $DEFAULT_COLOR"
    COLOR_LIST=("$DEFAULT_COLOR")
  fi
  info "selected: $_b$(
    IFS=', '
    echo "${COLOR_LIST[*]}"
  )$_x"
}

# Validates RAW_COLOR_ARGS against available_colors (warn + drop unknowns,
# fall back to DEFAULT_COLOR if nothing valid survives) and picks the single
# colour to install: the first surviving one in available_colors' canonical
# order, deterministic regardless of how --color listed them or duplicates.
# Used by the install path only — the generate-only path has no "active"
# colour, it just generates whatever the menu checked.
resolve_install_color() {
  local c valid=() bad=()
  for c in "${RAW_COLOR_ARGS[@]}"; do
    if available_colors | grep -qx "$c"; then valid+=("$c"); else bad+=("$c"); fi
  done
  if [ "${#bad[@]}" -gt 0 ]; then
    local b
    for b in "${bad[@]}"; do unknown_color_warning "$b"; done
  fi
  if [ "${#valid[@]}" -eq 0 ]; then
    warn "no valid colours selected — falling back to default: $DEFAULT_COLOR"
    valid=("$DEFAULT_COLOR")
  fi

  local canon picked=""
  while IFS= read -r canon; do
    local want
    for want in "${valid[@]}"; do
      [ "$canon" = "$want" ] && { picked="$canon"; break 2; }
    done
  done < <(available_colors)
  COLOR="${picked:-${valid[0]}}"
  RESOLVED_COLOR_ARG="--color=$COLOR"
}

# Every FAT/ESP-ish mount root worth searching, de-duplicated, existing only.
candidate_roots() {
  local roots=(/boot /boot/efi /boot/EFI /efi /boot/EFI/BOOT) r seen=""
  if command -v findmnt >/dev/null 2>&1; then
    while IFS= read -r r; do [ -n "$r" ] && roots+=("$r"); done \
      < <(findmnt -rno TARGET,FSTYPE 2>/dev/null | awk '$2 ~ /vfat|fat/ {print $1}')
  fi
  for r in "${roots[@]}"; do
    [ -d "$r" ] || continue
    case ",$seen," in *",$r,"*) continue ;; esac
    seen="$seen,$r"
    printf '%s\n' "$r"
  done
}

# rEFInd install dirs = a refind.conf (or refind_*.efi) next to a refind_*.efi
# binary. De-dup by the refind_*.efi inode, because the same ESP is often
# mounted at several of the candidate roots at once.
find_refind_installs() {
  local root efi dir key seen=""
  while IFS= read -r root; do
    while IFS= read -r efi; do
      dir="$(dirname "$efi")"
      key="$(stat -c '%d:%i' "$efi" 2>/dev/null || printf 'p:%s' "$efi")"
      case ",$seen," in *",$key,"*) continue ;; esac
      seen="$seen,$key"
      printf '%s\n' "$dir"
    done < <(find "$root" -maxdepth 5 -type f \( -iname 'refind_x64.efi' -o -iname 'refind_ia32.efi' -o -iname 'refind_aa64.efi' \) 2>/dev/null)
  done < <(candidate_roots)
}

is_refind_dir() {
  [ -d "$1" ] || return 1
  ls "$1"/refind_*.efi >/dev/null 2>&1 || ls "$1"/refind.conf >/dev/null 2>&1
}

# Resolves the rEFInd directory into the global REFIND_DIR, or dies with guidance.
REFIND_DIR=""
resolve_refind_dir() {
  if [ -n "$REFIND_DIR_OVERRIDE" ]; then
    is_refind_dir "$REFIND_DIR_OVERRIDE" \
      || die "--refind-dir '$REFIND_DIR_OVERRIDE' has no refind_*.efi or refind.conf in it."
    REFIND_DIR="$(cd "$REFIND_DIR_OVERRIDE" && pwd)"
    return 0
  fi

  local installs count
  mapfile -t installs < <(find_refind_installs)
  count=${#installs[@]}

  if [ "$count" -eq 0 ] && [ "$DEPLOY_REFIND" -eq 1 ]; then
    deploy_refind
    mapfile -t installs < <(find_refind_installs)
    count=${#installs[@]}
  fi

  if [ "$count" -eq 0 ]; then
    # In --dry-run we may just be unable to *read* a root-only ESP as the user.
    # Don't hard-fail a preview: guess a path so the plan still prints.
    if [ "$DRY_RUN" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
      local guess
      for guess in /boot/EFI/refind /boot/efi/EFI/refind /efi/EFI/refind /boot/EFI/BOOT; do
        REFIND_DIR="$guess"; break
      done
      warn "can't scan the ESP without root — guessing $REFIND_DIR for this preview."
      warn "run 'sudo $SELF --dry-run …' (or without --dry-run) for real detection."
      return 0
    fi
    { printf '%s[error]%s no rEFInd install found under: ' "$_r" "$_x"
      candidate_roots | paste -sd' '
      cat <<EOF

rEFInd itself is not on your EFI System Partition yet. Set it up first, then
re-run this:

  sudo refind-install            # Arch: pacman -S refind && sudo refind-install
  sudo $SELF --color $COLOR

Or let this script run refind-install for you:

  sudo $SELF --deploy-refind --color $COLOR

If rEFInd *is* installed somewhere unusual, point at it directly:

  sudo $SELF --refind-dir /path/to/dir/with/refind.conf --color $COLOR
EOF
    } >&2
    die "rEFInd not found."
  fi

  if [ "$count" -gt 1 ]; then
    warn "found more than one rEFInd install:"
    printf '    %s\n' "${installs[@]}" >&2
    die "ambiguous — pick one with:  sudo $SELF --refind-dir <path> --color $COLOR"
  fi

  REFIND_DIR="${installs[0]}"
}

deploy_refind() {
  step "deploying rEFInd (--deploy-refind)"
  command -v refind-install >/dev/null 2>&1 \
    || die "refind-install not found — install the 'refind' package first (e.g. pacman -S refind)."
  info "running: refind-install"
  refind-install || die "refind-install failed — see its output above; nothing of this theme was written."
  ok "refind-install finished"
}

# Print $conf with any prior managed block removed. Safe on a file that has none
# and on one with CRLF line endings.
strip_block() {
  awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" '
    { sub(/\r$/, "") }
    $0 == b { skip = 1; next }
    $0 == e { skip = 0; next }
    skip   { next }
    { print }
  ' "$1"
}

# ------------------------------------------------------------- validate --

validate_source() {
  step "checking theme source"
  local missing=0
  [ -f "$SCRIPT_DIR/theme.conf" ] || { warn "missing: theme.conf"; missing=1; }
  [ -d "$SCRIPT_DIR/icons" ] || { warn "missing: icons/"; missing=1; }
  [ -d "$SCRIPT_DIR/backgrounds" ] || { warn "missing: backgrounds/"; missing=1; }
  [ -f "$GENERATE_PY" ] || { warn "missing: tools/generate.py"; missing=1; }
  [ "$missing" -eq 0 ] \
    || die "theme source is incomplete — run this from inside the refind-lumen checkout."

  case "$BG" in
    dark | light) ;;
    *) die "unknown --background '$BG' (use: dark, light)." ;;
  esac
  [ -f "$(bg_image)" ] || die "$(bg_image) missing — regenerate with tools/generate.py."

  if ! available_colors | grep -qx "$COLOR"; then
    warn "colour '$COLOR' not found. Available:"
    available_colors | sed 's/^/    /' >&2
    die "pick one with --color, or run --list."
  fi
  local ld; ld="$(look_dir)"
  { [ -f "$ld/selection_big.png" ] && [ -f "$ld/selection_small.png" ] \
      && ls "$ld"/icons/*.png >/dev/null 2>&1; } \
    || die "$ld is incomplete — tools/generate.py did not produce it."
  ok "source OK — colour: $COLOR · background: $BG"
}

# After copying, make sure every path theme.conf points at actually resolves
# from refind.conf's directory, the way rEFInd will read it.
validate_installed() {
  local refind_dir="$1" conf="$1/$THEME_SUBDIR/theme.conf" directive value bad=0
  [ -f "$conf" ] || die "post-install check: $conf is missing."
  while read -r directive value _; do
    case "$directive" in
      icons_dir)
        [ -d "$refind_dir/$value" ] || { warn "theme.conf: icons_dir '$value' missing under $refind_dir"; bad=1; } ;;
      selection_big|selection_small|banner)
        [ -f "$refind_dir/$value" ] || { warn "theme.conf: $directive '$value' missing under $refind_dir"; bad=1; } ;;
    esac
  done < <(sed 's/\r$//' "$conf" | awk '!/^[[:space:]]*#/ && NF >= 2')
  [ "$bad" -eq 0 ] || die "post-install validation failed (paths above) — theme NOT wired into refind.conf."
  ok "all theme.conf paths resolve from $refind_dir"
}

# True if the installed theme dir already holds exactly what this run would
# write (same files, same chosen colour) — lets a re-run skip the ESP copy
# entirely instead of needlessly churning FAT files.
theme_files_current() {
  local target="$1" f rel ld
  [ -d "$target" ] || return 1
  ld="$(look_dir)"
  cmp -s "$SCRIPT_DIR/theme.conf"        "$target/theme.conf"          || return 1
  cmp -s "$(bg_image)"                   "$target/background.png"      || return 1
  cmp -s "$ld/selection_big.png"         "$target/selection_big.png"   || return 1
  cmp -s "$ld/selection_small.png"       "$target/selection_small.png" || return 1
  [ "$(find "$ld/icons" -maxdepth 1 -type f | wc -l)" \
      -eq "$(find "$target/icons" -maxdepth 1 -type f 2>/dev/null | wc -l)" ] || return 1
  while IFS= read -r f; do
    rel="${f#"$ld"/icons/}"
    cmp -s "$f" "$target/icons/$rel" || return 1
  done < <(find "$ld/icons" -type f)
  return 0
}

# ------------------------------------------------------------- install --

do_install() {
  local refind_dir conf target staging backup tmp body fresh=1

  step "generating theme assets"
  ensure_generated "$COLOR"

  step "locating rEFInd"
  resolve_refind_dir
  refind_dir="$REFIND_DIR"
  conf="$refind_dir/refind.conf"
  target="$refind_dir/$THEME_SUBDIR"
  ok "rEFInd dir: $refind_dir"
  if [ -f "$conf" ]; then info "refind.conf: present"; else info "refind.conf: absent (will be created)"; fi

  validate_source

  if [ -d "$target" ] && theme_files_current "$target"; then fresh=0; fi

  step "plan"
  info "install theme to : $target"
  info "colour           : $COLOR  ($(color_note "$COLOR"))"
  info "background        : $BG"
  info "refind.conf       : $conf"
  info "managed line      : $INCLUDE_LINE"
  if [ "$fresh" -eq 0 ]; then
    info "theme files       : already current — will only check refind.conf"
  elif [ -d "$target" ]; then
    info "theme files       : replacing (previous colour fully removed, no backup kept)"
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    warn "dry run — nothing changed."
    return 0
  fi

  if [ "$ASSUME_YES" -ne 1 ] && [ -t 0 ]; then
    printf '\nProceed? [y/N] '
    read -r reply
    case "$reply" in y | Y | yes | YES) ;; *) die "aborted." ;; esac
  fi

  ensure_writable "$refind_dir"

  if [ "$fresh" -eq 1 ]; then
    step "installing theme files"
    # Build the new theme in a staging dir first, then swap it in with a
    # single rm+mv — the previous colour (whatever it was) is fully replaced
    # and no backup is kept, so the ESP never accumulates old copies. Also
    # sweep any .previous/.new left by an older run or an earlier script
    # version.
    staging="$target.new"
    rm -rf "$staging" "$target.previous"
    mkdir -p "$staging"

    # plain cp only — never cp -a/-p and never `install -m`: the ESP is FAT,
    # which has no per-file ownership or mode, so anything that tries to
    # chown/chmod a file there is at best a no-op and at worst an error.
    local ld; ld="$(look_dir)"
    cp "$SCRIPT_DIR/theme.conf" "$staging/theme.conf"
    cp "$(bg_image)"            "$staging/background.png"
    cp -r "$ld/icons"           "$staging/icons"   # the set recoloured for this colour+bg
    cp "$ld/selection_big.png"   "$staging/selection_big.png"
    cp "$ld/selection_small.png" "$staging/selection_small.png"

    rm -rf "$target"
    mv "$staging" "$target"
    ok "installed theme to $target"
  else
    step "theme files already current — skipping copy"
  fi

  validate_installed "$refind_dir"

  step "wiring into refind.conf"
  local conf_created=0
  if [ ! -f "$conf" ]; then
    conf_created=1
    if [ -r /usr/share/refind/refind.conf-sample ]; then
      cp /usr/share/refind/refind.conf-sample "$conf"
      ok "created refind.conf from the stock sample"
    else
      printf '# created by Lumen install.sh\ntimeout 20\n' > "$conf"
      ok "created a minimal refind.conf"
    fi
  fi

  tmp="$(mktemp)"
  body="$(strip_block "$conf")"
  {
    [ -n "$body" ] && printf '%s\n\n' "$body"
    printf '%s\n%s\n%s\n' "$MARKER_BEGIN" "$INCLUDE_LINE" "$MARKER_END"
  } > "$tmp"

  if cmp -s "$tmp" "$conf"; then
    rm -f "$tmp"
    ok "refind.conf already up to date"
  elif [ "$conf_created" -eq 1 ]; then
    cat "$tmp" > "$conf"
    rm -f "$tmp"
    ok "refind.conf written (include line added)"
  else
    backup="$(unique_path "${conf}.lumen-backup")"
    cp "$conf" "$backup"
    cat "$tmp" > "$conf"      # write in place — keeps the FAT file's identity
    rm -f "$tmp"
    ok "refind.conf updated (backup: $backup)"
  fi

  trap - EXIT
  step "done"
  ok "Lumen installed · colour: $COLOR · background: $BG"
  info "reboot to see it. Restyle any time:  sudo $SELF --color <name> --background <dark|light>"
  info "remove it entirely:                 sudo $SELF --uninstall"
}

# --------------------------------------------------------- generate-only --

# The interactive-menu path: generate every picked colour into the
# persistent GENERATED_DIR cache and stop — no rEFInd/ESP/root involved at
# all. Installing a specific one afterwards is a separate `--color` run,
# which reuses whatever's already here instead of regenerating it.
do_generate_only() {
  step "generating selected colours"

  if [ "$DRY_RUN" -eq 1 ]; then
    warn "dry run — would generate: $(
      IFS=', '
      echo "${COLOR_LIST[*]}"
    ) -> $GENERATED_DIR"
    return 0
  fi

  ensure_generated "${COLOR_LIST[@]}"

  trap - EXIT
  step "done"
  ok "ready in $GENERATED_DIR — nothing was installed yet."
  info ""
  info "install one of these now:"
  local c
  for c in "${COLOR_LIST[@]}"; do
    info "  ./install.sh --color $c"
  done
}

# ----------------------------------------------------------- uninstall --

do_uninstall() {
  local refind_dir conf target backup

  step "locating rEFInd"
  resolve_refind_dir
  refind_dir="$REFIND_DIR"
  conf="$refind_dir/refind.conf"
  target="$refind_dir/$THEME_SUBDIR"
  ok "rEFInd dir: $refind_dir"

  if [ "$DRY_RUN" -eq 1 ]; then
    warn "dry run — would remove $target and the managed block from $conf."
    return 0
  fi

  ensure_writable "$refind_dir"

  step "removing"
  if [ -f "$conf" ] && grep -qF "$MARKER_BEGIN" "$conf"; then
    local body
    body="$(strip_block "$conf")"   # $(...) also trims the now-trailing blank line
    backup="$(unique_path "${conf}.lumen-backup")"
    cp "$conf" "$backup"
    printf '%s\n' "$body" > "$conf"
    ok "managed block removed from refind.conf (backup: $backup)"
  else
    info "no managed block in refind.conf — leaving it alone"
  fi

  # Guard the rm: only ever our own exact paths, never anything else.
  if [ "$target" = "$refind_dir/$THEME_SUBDIR" ] && [ -d "$target" ]; then
    rm -rf "$target"
    ok "removed $target"
  else
    info "$target not present — nothing to remove"
  fi
  # .previous is from an older version of this script (it no longer keeps
  # one); .new would only exist if a run crashed mid-swap. Sweep both.
  if [ -d "$target.previous" ]; then
    rm -rf "$target.previous"
    ok "removed $target.previous"
  fi
  if [ -d "$target.new" ]; then
    rm -rf "$target.new"
    ok "removed $target.new"
  fi
  # tidy the themes/ parent, but only if empty (the user may keep other themes)
  if rmdir "$refind_dir/themes" 2>/dev/null; then
    info "removed now-empty themes/"
  fi

  trap - EXIT
  step "done"
  ok "Lumen uninstalled"
  info "refind.conf backups (*.lumen-backup-*) were left for you to delete"
}

# ------------------------------------------------------------- parsing --

while [ $# -gt 0 ]; do
  case "$1" in
    --color)            add_color_arg "${2:-}"; shift 2 ;;
    --color=*)          add_color_arg "${1#*=}"; shift ;;
    --background | --bg) BG="$(normalise_bg "${2:-}")"; shift 2 ;;
    --background=* | --bg=*) BG="$(normalise_bg "${1#*=}")"; shift ;;
    --refind-dir)       REFIND_DIR_OVERRIDE="${2:-}"; shift 2 ;;
    --refind-dir=*)     REFIND_DIR_OVERRIDE="${1#*=}"; shift ;;
    --dry-run)          DRY_RUN=1; shift ;;
    --yes | -y)         ASSUME_YES=1; shift ;;
    --deploy-refind)    DEPLOY_REFIND=1; shift ;;
    --uninstall)        UNINSTALL=1; shift ;;
    --list | --list-colors) LIST=1; shift ;;
    -h | --help)        usage; trap - EXIT; exit 0 ;;
    *)                  die "unknown option: $1  (see --help)" ;;
  esac
done

# A cheap sanity check on the checkout before we bother with anything else —
# the authoritative validate_source() call is inside do_install (post-sudo).
if [ ! -d "$SCRIPT_DIR/icons" ] || [ ! -f "$GENERATE_PY" ]; then
  die "icons/ or tools/generate.py missing here — run this from inside the refind-lumen checkout."
fi

if [ "$LIST" -eq 1 ]; then
  check_dependencies
  printf '%scolours%s  (--color)\n\n' "$_b" "$_x"
  while IFS= read -r c; do printf '  %-16s %s\n' "$c" "$(color_note "$c")"; done < <(available_colors)
  printf '\n%sbackgrounds%s  (--background)\n\n  %-16s %s\n  %-16s %s\n' \
    "$_b" "$_x" dark "black (default)" light "near-white; icons + selection arc go dark"
  trap - EXIT
  exit 0
fi

if [ "$UNINSTALL" -eq 1 ]; then
  escalate_if_needed
  do_uninstall
  exit 0
fi

check_dependencies

if [ "${#RAW_COLOR_ARGS[@]}" -gt 0 ]; then
  # --color given: install exactly that one (reusing GENERATED_DIR if it's
  # already there). Needs the ESP, so it may need root.
  resolve_install_color
  escalate_if_needed
  do_install
elif [ -t 0 ]; then
  # No --color, a terminal is attached: pick colours to generate. This never
  # touches rEFInd, so it never needs root — no escalate_if_needed here.
  interactive_color_menu
  do_generate_only
else
  # No --color, no terminal (piped/scripted run): keep the old plain
  # default so a one-liner install still just works.
  COLOR="$DEFAULT_COLOR"
  RESOLVED_COLOR_ARG="--color=$COLOR"
  escalate_if_needed
  do_install
fi
