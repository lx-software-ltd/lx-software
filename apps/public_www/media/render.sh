#!/usr/bin/env bash
# Render the harbour master to a 0.25x silent loop and the delivery files.
# Measured on the uploaded master: slow 19.875s, loop 18.375s, no audio.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/build" "$ROOT/../public/media"

ffmpeg -y -i "$ROOT/source/hk-harbour-master.mp4" -an \
  -vf "minterpolate=fps=96:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,setpts=4*PTS,format=yuv420p" \
  -r 24 -c:v libx264 -preset slow -crf 18 -movflags +faststart \
  "$ROOT/build/hk-harbour-slow.mp4"

D="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$ROOT/build/hk-harbour-slow.mp4")"
T="$(python3 -c "print(round($D - 1.5, 3))")"

ffmpeg -y -i "$ROOT/build/hk-harbour-slow.mp4" -filter_complex "
  [0:v]split[m][t];
  [t]trim=start=$T,setpts=PTS-STARTPTS[tail];
  [m]trim=end=$T,setpts=PTS-STARTPTS[main];
  [tail][main]xfade=transition=fade:duration=1.5:offset=0[v]" \
  -map "[v]" -c:v libx264 -preset slow -crf 18 -movflags +faststart \
  "$ROOT/build/hk-harbour-loop.mp4"

OUT="$ROOT/../public/media"
ffmpeg -y -i "$ROOT/build/hk-harbour-loop.mp4" \
  -c:v libx264 -profile:v high -level 4.1 -pix_fmt yuv420p -crf 23 -preset slow \
  -g 48 -keyint_min 48 -sc_threshold 0 -movflags +faststart \
  "$OUT/hk-harbour-v1-720.mp4"
ffmpeg -y -i "$ROOT/build/hk-harbour-loop.mp4" -vf "scale=-2:480" \
  -c:v libx264 -profile:v high -level 4.1 -pix_fmt yuv420p -crf 23 -preset slow \
  -g 48 -keyint_min 48 -sc_threshold 0 -movflags +faststart \
  "$OUT/hk-harbour-v1-480.mp4"
ffmpeg -y -i "$ROOT/build/hk-harbour-loop.mp4" \
  -c:v libsvtav1 -crf 34 -preset 8 -g 48 -pix_fmt yuv420p \
  "$OUT/hk-harbour-v1-720.webm"
ffmpeg -y -i "$ROOT/build/hk-harbour-loop.mp4" -vf "scale=-2:480" \
  -c:v libsvtav1 -crf 34 -preset 8 -g 48 -pix_fmt yuv420p \
  "$OUT/hk-harbour-v1-480.webm"
ffmpeg -y -i "$ROOT/build/hk-harbour-loop.mp4" -frames:v 1 -q:v 3 \
  "$OUT/hk-harbour-v1-poster.jpg"
ffmpeg -y -i "$ROOT/build/hk-harbour-loop.mp4" -frames:v 1 -c:v libwebp -quality 80 \
  "$OUT/hk-harbour-v1-poster.webp"
