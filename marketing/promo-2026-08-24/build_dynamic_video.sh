#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
FRAMES="$HERE/desktop-frames"
WORK="$HERE/dynamic-work"
OUT="$HERE/17同游-网页端完整使用演示-动态增强版.mp4"
COVER="$HERE/17同游-动态增强版封面.jpg"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="/tmp/17tongyou-promo-dynamic-profile"
CONTACT="$FRAMES/contact-sheet-v3.png"

mkdir -p "$WORK"
node "$HERE/make_desktop_frames.js"

if [[ ! -s "$CONTACT" ]]; then
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run \
    --disable-background-networking --disable-component-update --disable-default-apps \
    --user-data-dir="$PROFILE" --force-device-scale-factor=1 --window-size=11520,3240 \
    --screenshot="$CONTACT" "file://$FRAMES/contact-sheet-v3.html" \
    >"$HERE/chrome-render-dynamic.log" 2>&1 &
  chrome_pid=$!
  for _ in {1..160}; do
    [[ -s "$CONTACT" ]] && break
    sleep 0.25
  done
  [[ -s "$CONTACT" ]]
  kill "$chrome_pid" 2>/dev/null || true
  wait "$chrome_pid" 2>/dev/null || true
fi

for i in {0..17}; do
  n="$(printf '%02d' $((i + 1)))"
  x=$(((i % 6) * 1920))
  y=$(((i / 6) * 1080))
  ffmpeg -hide_banner -loglevel error -y -i "$CONTACT" \
    -vf "crop=1920:1080:$x:$y" -frames:v 1 "$FRAMES/$n.png"
done

# Stable scene durations. The page itself does not zoom, preventing text and border jitter.
durations=(2.2 0.7 0.7 0.7 1.4 1.8 1.8 1.8 2.5 4.0 3.5 3.0 4.8 3.8 3.2 3.5 3.7 3.5)

for i in {1..18}; do
  n="$(printf '%02d' "$i")"
  ffmpeg -hide_banner -loglevel error -y -loop 1 -t "${durations[$((i-1))]}" \
    -i "$FRAMES/$n.png" -vf "fps=30,format=yuv420p" \
    -an -c:v libx264 -preset veryfast -crf 18 -r 30 "$WORK/scene-$n.mp4"
done

# Major chapter changes use a horizontal card flip. Minor state changes use short,
# low-motion transitions so the UI stays readable.
for i in {1..17}; do
  a="$(printf '%02d' "$i")"
  b="$(printf '%02d' $((i + 1)))"
  case "$i" in
    5|8|12|16|17)
      ffmpeg -hide_banner -loglevel error -y \
        -loop 1 -t 0.30 -i "$FRAMES/$a.png" \
        -loop 1 -t 0.30 -i "$FRAMES/$b.png" \
        -filter_complex "[0:v]trim=duration=0.30,setpts=PTS-STARTPTS,scale=w='max(8,trunc(iw*(1-t/0.30)/2)*2)':h=1080:eval=frame,pad=1920:1080:(ow-iw)/2:0:color=#171a36:eval=frame[a];[1:v]trim=duration=0.30,setpts=PTS-STARTPTS,scale=w='max(8,trunc(iw*(t/0.30)/2)*2)':h=1080:eval=frame,pad=1920:1080:(ow-iw)/2:0:color=#171a36:eval=frame[b];[a][b]concat=n=2:v=1:a=0,format=yuv420p[v]" \
        -map '[v]' -an -r 30 -c:v libx264 -preset veryfast -crf 18 "$WORK/trans-$a-$b.mp4"
      ;;
    9|10|11)
      ffmpeg -hide_banner -loglevel error -y \
        -loop 1 -t 0.24 -i "$FRAMES/$a.png" -loop 1 -t 0.24 -i "$FRAMES/$b.png" \
        -filter_complex "[0:v][1:v]xfade=transition=slideup:duration=0.24:offset=0,format=yuv420p[v]" \
        -map '[v]' -t 0.24 -an -r 30 -c:v libx264 -preset veryfast -crf 18 "$WORK/trans-$a-$b.mp4"
      ;;
    13|14|15)
      ffmpeg -hide_banner -loglevel error -y \
        -loop 1 -t 0.24 -i "$FRAMES/$a.png" -loop 1 -t 0.24 -i "$FRAMES/$b.png" \
        -filter_complex "[0:v][1:v]xfade=transition=smoothleft:duration=0.24:offset=0,format=yuv420p[v]" \
        -map '[v]' -t 0.24 -an -r 30 -c:v libx264 -preset veryfast -crf 18 "$WORK/trans-$a-$b.mp4"
      ;;
    *)
      ffmpeg -hide_banner -loglevel error -y \
        -loop 1 -t 0.18 -i "$FRAMES/$a.png" -loop 1 -t 0.18 -i "$FRAMES/$b.png" \
        -filter_complex "[0:v][1:v]xfade=transition=dissolve:duration=0.18:offset=0,format=yuv420p[v]" \
        -map '[v]' -t 0.18 -an -r 30 -c:v libx264 -preset veryfast -crf 18 "$WORK/trans-$a-$b.mp4"
      ;;
  esac
done

MANIFEST="$WORK/manifest.txt"
: > "$MANIFEST"
for i in {1..18}; do
  n="$(printf '%02d' "$i")"
  printf "file '%s'\n" "$WORK/scene-$n.mp4" >> "$MANIFEST"
  if [[ "$i" -lt 18 ]]; then
    b="$(printf '%02d' $((i + 1)))"
    printf "file '%s'\n" "$WORK/trans-$n-$b.mp4" >> "$MANIFEST"
  fi
done

ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$MANIFEST" \
  -an -c:v libx264 -preset medium -crf 18 -r 30 -movflags +faststart "$WORK/video-only.mp4"

duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/video-only.mp4")"
ffmpeg -hide_banner -loglevel error -y -i "$WORK/video-only.mp4" \
  -f lavfi -t "$duration" -i "aevalsrc=0.022*sin(2*PI*196*t)+0.013*sin(2*PI*294*t)+0.006*sin(2*PI*49*t)*(0.55+0.45*sin(2*PI*2*t)):s=48000" \
  -filter_complex "[1:a]afade=t=in:st=0:d=1.2,afade=t=out:st=$(awk -v d="$duration" 'BEGIN{printf "%.2f",d-2}'):d=2,aecho=0.7:0.18:60:0.16,volume=0.72[a]" \
  -map 0:v -map '[a]' -c:v copy -c:a aac -b:a 160k -shortest -movflags +faststart "$OUT"

ffmpeg -hide_banner -loglevel error -y -ss 49 -i "$OUT" -frames:v 1 -q:v 2 "$COVER"
echo "$OUT"

