#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VIDEO="$HERE/17同游-网页端完整使用演示-动态增强版.mp4"
test -s "$VIDEO"
probe="$(ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate -show_entries format=duration -of default=noprint_wrappers=1 "$VIDEO")"
echo "$probe"
grep -q '^codec_name=h264$' <<<"$probe"
grep -q '^codec_name=aac$' <<<"$probe"
grep -q '^width=1920$' <<<"$probe"
grep -q '^height=1080$' <<<"$probe"
grep -q '^r_frame_rate=30/1$' <<<"$probe"
duration="$(awk -F= '/^duration=/{print $2}' <<<"$probe")"
awk -v d="$duration" 'BEGIN { exit !(d >= 48 && d <= 58) }'

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
ffmpeg -hide_banner -loglevel error -y -ss 28.5 -i "$VIDEO" -frames:v 1 "$tmp_dir/a.png"
ffmpeg -hide_banner -loglevel error -y -ss 29.5 -i "$VIDEO" -frames:v 1 "$tmp_dir/b.png"
psnr_line="$(ffmpeg -hide_banner -i "$tmp_dir/a.png" -i "$tmp_dir/b.png" -lavfi psnr -f null - 2>&1 | grep 'average:')"
psnr="$(sed -E 's/.*average:([0-9.]+).*/\1/' <<<"$psnr_line")"
awk -v p="$psnr" 'BEGIN { exit !(p >= 60) }'
echo "PASS: stable 1920x1080, H.264/AAC, 30fps, ${duration}s, static-scene PSNR ${psnr}dB"

