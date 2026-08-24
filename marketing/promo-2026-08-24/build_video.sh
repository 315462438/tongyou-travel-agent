#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
FRAMES="$HERE/frames"
OUT="$HERE/17同游-社交平台宣传片-竖屏.mp4"
COVER="$HERE/17同游-宣传片封面.jpg"

node "$HERE/make_frames.js"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="/tmp/17tongyou-promo-chrome-profile"
CONTACT="$FRAMES/contact-sheet.png"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run \
  --disable-background-networking --disable-component-update --disable-default-apps \
  --user-data-dir="$PROFILE" --force-device-scale-factor=1 --window-size=8640,1920 \
  --screenshot="$CONTACT" "file://$FRAMES/contact-sheet.html"

for i in {0..7}; do
  n="$(printf '%02d' $((i + 1)))"
  ffmpeg -hide_banner -loglevel error -y -i "$CONTACT" \
    -vf "crop=1080:1920:$((i * 1080)):0" -frames:v 1 "$FRAMES/$n.png"
done

ffmpeg -hide_banner -loglevel error -y \
  -loop 1 -t 5 -i "$FRAMES/01.png" \
  -loop 1 -t 5 -i "$FRAMES/02.png" \
  -loop 1 -t 5 -i "$FRAMES/03.png" \
  -loop 1 -t 5 -i "$FRAMES/04.png" \
  -loop 1 -t 5 -i "$FRAMES/05.png" \
  -loop 1 -t 5 -i "$FRAMES/06.png" \
  -loop 1 -t 5 -i "$FRAMES/07.png" \
  -loop 1 -t 5 -i "$FRAMES/08.png" \
  -f lavfi -t 35.8 -i "aevalsrc=0.030*sin(2*PI*220*t)+0.018*sin(2*PI*330*t)+0.010*sin(2*PI*440*t):s=48000" \
  -filter_complex "\
    [0:v]scale=1080:1920,zoompan=z='min(zoom+0.00020,1.03)':d=150:s=1080x1920:fps=30,setsar=1[v0];\
    [1:v]scale=1080:1920,zoompan=z='min(zoom+0.00016,1.025)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1080x1920:fps=30,setsar=1[v1];\
    [2:v]scale=1080:1920,zoompan=z='min(zoom+0.00022,1.033)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1080x1920:fps=30,setsar=1[v2];\
    [3:v]scale=1080:1920,zoompan=z='min(zoom+0.00017,1.026)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1080x1920:fps=30,setsar=1[v3];\
    [4:v]scale=1080:1920,zoompan=z='min(zoom+0.00018,1.027)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1080x1920:fps=30,setsar=1[v4];\
    [5:v]scale=1080:1920,zoompan=z='min(zoom+0.00018,1.027)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1080x1920:fps=30,setsar=1[v5];\
    [6:v]scale=1080:1920,zoompan=z='min(zoom+0.00018,1.027)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1080x1920:fps=30,setsar=1[v6];\
    [7:v]scale=1080:1920,zoompan=z='min(zoom+0.00014,1.021)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1080x1920:fps=30,setsar=1[v7];\
    [v0][v1]xfade=transition=fade:duration=.6:offset=4.4[x1];\
    [x1][v2]xfade=transition=smoothleft:duration=.6:offset=8.8[x2];\
    [x2][v3]xfade=transition=fade:duration=.6:offset=13.2[x3];\
    [x3][v4]xfade=transition=slideleft:duration=.6:offset=17.6[x4];\
    [x4][v5]xfade=transition=fade:duration=.6:offset=22.0[x5];\
    [x5][v6]xfade=transition=smoothleft:duration=.6:offset=26.4[x6];\
    [x6][v7]xfade=transition=fade:duration=.6:offset=30.8,format=yuv420p[vout];\
    [8:a]afade=t=in:st=0:d=1.2,afade=t=out:st=33.8:d=2,volume=.75[aout]" \
  -map "[vout]" -map "[aout]" -t 35.8 \
  -c:v libx264 -preset medium -crf 18 -profile:v high -level 4.1 \
  -c:a aac -b:a 160k -movflags +faststart "$OUT"

ffmpeg -hide_banner -loglevel error -y -ss 33.5 -i "$OUT" -frames:v 1 -q:v 2 "$COVER"
echo "$OUT"
