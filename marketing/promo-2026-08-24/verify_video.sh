#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VIDEO="$HERE/17同游-社交平台宣传片-竖屏.mp4"

test -s "$VIDEO"
probe="$(ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate -show_entries format=duration -of default=noprint_wrappers=1 "$VIDEO")"
echo "$probe"
grep -q '^codec_name=h264$' <<<"$probe"
grep -q '^width=1080$' <<<"$probe"
grep -q '^height=1920$' <<<"$probe"
grep -q '^r_frame_rate=30/1$' <<<"$probe"
duration="$(awk -F= '/^duration=/{print $2}' <<<"$probe")"
awk -v d="$duration" 'BEGIN { exit !(d >= 30 && d <= 45) }'
echo "PASS: 1080x1920, H.264, 30fps, ${duration}s"

