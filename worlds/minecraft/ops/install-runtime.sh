#!/usr/bin/env bash
# ops/install-runtime.sh — put the world's runtimes on the Thor, locally.
#
# Nothing here installs anything system-wide (Casey's rule for the JDK,
# and the same discipline for Node so the two agree on versions). Every
# archive is checked against its published sha256 before it is unpacked,
# so a truncated download cannot become a server that starts "sometimes".
#
#   ops/install-runtime.sh            # install whatever is missing
#   ops/install-runtime.sh --verify   # check what is there, install nothing
#
# The undo for all of it: rm -rf runtime/ and every listener is gone.
set -euo pipefail

. "$(dirname "$0")/env.sh"

DL="$AW_RUNTIME/dl"
mkdir -p "$DL"

# --- the versions, in one place ---------------------------------------------
# JDK 25 (Temurin), aarch64: the JDK the Minecraft 26.x line asks for.
# Paper says so out loud and refuses to start on anything older.
JDK25_FILE="OpenJDK25U-jdk_aarch64_linux_hotspot_25.0.5_8.tar.gz"
JDK25_URL="https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/$JDK25_FILE"
JDK25_SHA="bb5b2ded252f21c6090cf780b0a408ad0d83bbb557e702955643557f13231880"

# JDK 21 (Temurin), aarch64: the JDK the Minecraft 1.21.x line asks for.
# It is here so the world can be moved between the two lines with one
# line changed in ops/env.sh, and so that fallback is real and tested
# rather than a claim in a README.
JDK21_FILE="OpenJDK21U-jdk_aarch64_linux_hotspot_21.0.13_9.tar.gz"
JDK21_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/$JDK21_FILE"
JDK21_SHA="e3522e707fc7dbe2a72c30746b1e7068301a0213ecd213d4491f35a14eb55578"

# Node 24 LTS: the bots and the browser view are Node programs, and this
# box has the runtime but no package manager.
NODE_VERSION="v24.22.2"
NODE_FILE="node-v24.22.2-linux-arm64.tar.xz"
NODE_URL="https://nodejs.org/dist/$NODE_VERSION/$NODE_FILE"
NODE_SHA="eb187837a2230d4047161ac0be008584e16b46f726e9c9490ee35dc6b17d9ba8"

# Paper 26.1.2 build 74 (STABLE). 26.1 is the newest protocol mineflayer
# speaks, so this is the newest server the bots and the humans can share.
# The 1.21.11 build is the other end of the same choice: it is what the
# 1.21.x line runs, on JDK 21.
PAPER_FILE="paper-26.1.2-74.jar"
PAPER_URL="https://fill-data.papermc.io/v1/objects/1d70b1dab9cf4a6de615209a536f3a45a2186240253c428213ce2188ab95e5f7/$PAPER_FILE"
PAPER_SHA="1d70b1dab9cf4a6de615209a536f3a45a2186240253c428213ce2188ab95e5f7"

PAPER_121_FILE="paper-1.21.11-132.jar"
PAPER_121_URL="https://fill-data.papermc.io/v1/objects/5ffef465eeeb5f2a3c23a24419d97c51afd7dbb4923ff42df9a3f58bba1ccfba/$PAPER_121_FILE"
PAPER_121_SHA="5ffef465eeeb5f2a3c23a24419d97c51afd7dbb4923ff42df9a3f58bba1ccfba"

# Geyser + Floodgate: the Bedrock door. Optional (Casey's answer: his
# family runs Bedrock on the tablets and phones).
GEYSER_FILE="Geyser-Spigot.jar"
GEYSER_URL="https://download.geysermc.org/v2/projects/geyser/versions/2.12.1/builds/1273/downloads/spigot"
GEYSER_SHA="218f57088fd7a147f670c489377da2341fc51f1867b2c36ed181f39c9f379b59"
FLOODGATE_FILE="floodgate-spigot.jar"
FLOODGATE_URL="https://download.geysermc.org/v2/projects/floodgate/versions/2.2.5/builds/120/downloads/spigot"
FLOODGATE_SHA="3b69f4587bd683f58589c967ce0a2fbf07e855badf3fd880fe3519b1aebcaa2c"

# The voices: Kokoro-82M v1.2 int8 (Apache-2.0) and the four voice
# files the spectator page speaks with. The page loads them from the
# viewer itself (viewer/public/paradee/), never from the internet —
# after the first load the Orin's Firefox needs no network at all. The
# voices ship inside the kokoro-js package; the model is mirrored from
# the model hub so the checksum is ours.
KOKORO_BASE="https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
KOKORO_DIR="$AW_ROOT/viewer/public/paradee/models/onnx-community/Kokoro-82M-v1.0-ONNX"
KOKORO_MODEL_SHA="fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478"

VERIFY_ONLY=0
[ "${1:-}" = "--verify" ] && VERIFY_ONLY=1

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

# fetch <url> <file> <sha256>
fetch() {
    local url="$1" file="$2" want="$3"
    local path="$DL/$file"
    if [ -f "$path" ]; then
        local have
        have="$(sha256sum "$path" | cut -d' ' -f1)"
        if [ "$have" = "$want" ]; then
            say "$file: already here and the checksum matches"
            return 0
        fi
        warn "$file: checksum differs ($have), fetching again"
        rm -f "$path"
    fi
    if [ "$VERIFY_ONLY" = "1" ]; then
        warn "$file: missing (verify mode, not fetching)"
        return 1
    fi
    say "downloading $file"
    curl -sSL --retry 3 --retry-delay 2 -o "$path.part" "$url"
    mv "$path.part" "$path"
    local have
    have="$(sha256sum "$path" | cut -d' ' -f1)"
    [ "$have" = "$want" ] || die "$file: sha256 mismatch (want $want, got $have)"
    say "$file: sha256 ok"
}

# --- the JDKs ---------------------------------------------------------------
if [ ! -x "$AW_JDK25/bin/java" ] || [ "$VERIFY_ONLY" = "1" ]; then
    if fetch "$JDK25_URL" "$JDK25_FILE" "$JDK25_SHA"; then
        say "unpacking JDK 25 into $AW_JDK25"
        rm -rf "$AW_JDK25"
        mkdir -p "$AW_JDK25"
        tar xzf "$DL/$JDK25_FILE" -C "$AW_JDK25" --strip-components=1
    fi
fi
if [ ! -x "$AW_JDK21/bin/java" ] || [ "$VERIFY_ONLY" = "1" ]; then
    if fetch "$JDK21_URL" "$JDK21_FILE" "$JDK21_SHA"; then
        say "unpacking JDK 21 into $AW_JDK21"
        rm -rf "$AW_JDK21"
        mkdir -p "$AW_JDK21"
        tar xzf "$DL/$JDK21_FILE" -C "$AW_JDK21" --strip-components=1
    fi
fi
[ -x "$AW_JDK25/bin/java" ] && say "java 25: $("$AW_JDK25/bin/java" -version 2>&1 | head -1)"
[ -x "$AW_JDK21/bin/java" ] && say "java 21: $("$AW_JDK21/bin/java" -version 2>&1 | head -1)"
[ -x "$AW_JDK/bin/java" ] && say "the world runs on: $("$AW_JDK/bin/java" -version 2>&1 | head -1)"

# --- Node -------------------------------------------------------------------
if [ ! -x "$AW_NODE/bin/node" ] || [ "$VERIFY_ONLY" = "1" ]; then
    if fetch "$NODE_URL" "$NODE_FILE" "$NODE_SHA"; then
        say "unpacking Node into $AW_NODE"
        rm -rf "$AW_NODE"
        mkdir -p "$AW_NODE"
        tar xJf "$DL/$NODE_FILE" -C "$AW_NODE" --strip-components=1
    fi
fi
[ -x "$AW_NODE/bin/node" ] && say "node: $("$AW_NODE/bin/node" -v)"

# --- Paper ------------------------------------------------------------------
fetch "$PAPER_URL" "$PAPER_FILE" "$PAPER_SHA" || true
fetch "$PAPER_121_URL" "$PAPER_121_FILE" "$PAPER_121_SHA" || true

# --- Geyser + Floodgate -----------------------------------------------------
fetch "$GEYSER_URL" "$GEYSER_FILE" "$GEYSER_SHA" || true
fetch "$FLOODGATE_URL" "$FLOODGATE_FILE" "$FLOODGATE_SHA" || true

# --- the voices -------------------------------------------------------------
# The mirror the page speaks from: the model, the configs, and the four
# voices. The voices come out of the npm package (cd viewer && npm
# install), so they are here only when it has run at least once.
mkdir -p "$KOKORO_DIR/onnx" "$KOKORO_DIR/voices"
for conf in config.json preprocessor_config.json processor_config.json \
            generation_config.json tokenizer.json tokenizer_config.json chat_template.json; do
    if [ ! -s "$KOKORO_DIR/$conf" ] && [ "$VERIFY_ONLY" != "1" ]; then
        curl -sSL --retry 3 -o "$KOKORO_DIR/$conf" "$KOKORO_BASE/$conf" || true
    fi
    [ -s "$KOKORO_DIR/$conf" ] || warn "$conf: missing from the voice mirror"
done
if [ ! -s "$KOKORO_DIR/onnx/model_quantized.onnx" ]; then
    if [ "$VERIFY_ONLY" = "1" ]; then
        warn "the voice model is missing (verify mode, not fetching)"
    else
        say "downloading the voice model (92 MB)"
        curl -sSL --retry 3 -o "$KOKORO_DIR/onnx/model_quantized.onnx.part" "$KOKORO_BASE/onnx/model_quantized.onnx"
        mv "$KOKORO_DIR/onnx/model_quantized.onnx.part" "$KOKORO_DIR/onnx/model_quantized.onnx"
    fi
fi
if [ -s "$KOKORO_DIR/onnx/model_quantized.onnx" ]; then
    have="$(sha256sum "$KOKORO_DIR/onnx/model_quantized.onnx" | cut -d' ' -f1)"
    [ "$have" = "$KOKORO_MODEL_SHA" ] || die "the voice model's checksum differs (want $KOKORO_MODEL_SHA, got $have)"
    say "the voice model: mirrored and the checksum matches"
fi
KOKORO_PKG="$AW_ROOT/viewer/node_modules/kokoro-js/voices"
for voice in af_heart bf_isabella am_puck bm_fable; do
    if [ -f "$KOKORO_PKG/$voice.bin" ]; then
        cmp -s "$KOKORO_PKG/$voice.bin" "$KOKORO_DIR/voices/$voice.bin" 2>/dev/null || \
            cp "$KOKORO_PKG/$voice.bin" "$KOKORO_DIR/voices/$voice.bin"
    else
        [ -s "$KOKORO_DIR/voices/$voice.bin" ] || warn "voice $voice: not in the mirror (run: cd viewer && npm install)"
    fi
done

say "runtime is under $AW_RUNTIME"
