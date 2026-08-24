#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
FRAMES="$HERE/desktop-frames"
OUT="$HERE/17同游-网页端完整使用演示-16x9.mp4"
COVER="$HERE/17同游-网页端宣传片封面.jpg"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="/tmp/17tongyou-promo-desktop-profile"

node "$HERE/make_desktop_frames.js"
CONTACT="$FRAMES/contact-sheet-v2.png"
if [[ ! -s "$CONTACT" ]]; then
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run \
    --disable-background-networking --disable-component-update --disable-default-apps \
    --user-data-dir="$PROFILE" --force-device-scale-factor=1 --window-size=9600,3240 \
    --screenshot="$CONTACT" "file://$FRAMES/contact-sheet.html" \
    >"$HERE/chrome-render.log" 2>&1 &
  chrome_pid=$!
  for _ in {1..120}; do
    [[ -s "$CONTACT" ]] && break
    sleep 0.25
  done
  [[ -s "$CONTACT" ]]
  kill "$chrome_pid" 2>/dev/null || true
  wait "$chrome_pid" 2>/dev/null || true
fi

for i in {0..14}; do
  n="$(printf '%02d' $((i + 1)))"
  x=$(((i % 5) * 1920))
  y=$(((i / 5) * 1080))
  ffmpeg -hide_banner -loglevel error -y -i "$CONTACT" \
    -vf "crop=1920:1080:$x:$y" -frames:v 1 "$FRAMES/$n.png"
done

durations=(3.0 1.0 1.0 1.0 2.0 2.2 2.2 2.2 3.0 5.5 4.5 6.0 5.0 5.0 4.0)
input_args=()
filters=""
for i in {0..14}; do
  n="$(printf '%02d' $((i + 1)))"
  input_args+=( -loop 1 -t "${durations[$i]}" -i "$FRAMES/$n.png" )
  filters+="[$i:v]scale=1920:1080,zoompan=z='min(zoom+0.00010,1.018)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=$(awk -v d="${durations[$i]}" 'BEGIN{printf "%d",d*30}'):s=1920x1080:fps=30,setsar=1[v$i];"
done

offset=2.65
prev="v0"
transitions=(fade fade fade fade smoothleft fade fade smoothleft fade slideup fade smoothleft fade fade)
for i in {1..14}; do
  out="x$i"
  filters+="[$prev][v$i]xfade=transition=${transitions[$((i-1))]}:duration=0.35:offset=$offset[$out];"
  prev="$out"
  offset="$(awk -v o="$offset" -v d="${durations[$i]}" 'BEGIN{printf "%.2f",o+d-0.35}')"
done
filters+="[$prev]format=yuv420p[vout];[15:a]afade=t=in:st=0:d=1.2,afade=t=out:st=40.7:d=2,volume=.7[aout]"

ffmpeg -hide_banner -loglevel error -y "${input_args[@]}" \
  -f lavfi -t 42.7 -i "aevalsrc=0.026*sin(2*PI*196*t)+0.016*sin(2*PI*294*t)+0.009*sin(2*PI*392*t):s=48000" \
  -filter_complex "$filters" -map '[vout]' -map '[aout]' -t 42.7 \
  -c:v libx264 -preset medium -crf 18 -profile:v high -level 4.1 \
  -c:a aac -b:a 160k -movflags +faststart "$OUT"

ffmpeg -hide_banner -loglevel error -y -ss 40.5 -i "$OUT" -frames:v 1 -q:v 2 "$COVER"
echo "$OUT"
