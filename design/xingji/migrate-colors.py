"""把 index.css 里的硬编码颜色映射到「行记」token。

闸门是 **ΔL* ≤ 6（保明度、换色温）**，不是 ΔE——冷灰换暖墨 ΔE 天然 ~20，
用 ΔE 卡会把改造意图本身卡死；而真正会出事的是明度变了（对比度靠明度）。
"""
import re, sys, colorsys
sys.path.insert(0, '/tmp')
from palette import to_lab, to_rgb

RAMP = [('--x-n100','#FFFEFB'),('--x-n96','#F7F3EA'),('--x-n88','#E3DCC7'),
        ('--x-n78','#CDBF9C'),('--x-n68','#B2A583'),('--x-n60','#9C8F6F'),
        ('--x-n50','#827659'),('--x-n41','#6A6046'),('--x-n30','#4E4635'),
        ('--x-n20','#362F26'),('--x-n12','#241F1B')]
RAMP_L = [(n, h, to_lab(to_rgb(h))[0]) for n, h in RAMP]

# 不动的选择器：海报是调色板来源（改了是自我循环）、特效组件靠渐变、
# 地图 marker 色要与高德静态图 URL 参数一致。
PROTECT = re.compile(r'\.rmap-|\.poster-|\.rec-|aurora|iridescence|side-ray|'
                     r'\.auth-sky|'  # 表意色：天空不是品牌蓝
                     r'\.immersive|marker|legend|--rc\b|\.brand-mark', re.I)

ROLE = {
    'pine':     [('--x-pine-96','#E8F7ED'),('--x-pine-51','#5B826B'),('--x-pine-90','#D4E7DB'),('--x-pine-74','#A1BDAB'),('--x-pine-58','#70947E'),
                 ('--x-pine-44','#467158'),('--x-pine-30','#274E39')],
    'cinnabar': [('--x-cinnabar-96','#FFE8DF'),('--x-cinnabar-51','#C55749'),('--x-cinnabar-90','#FFD5C9'),('--x-cinnabar-74','#F4A192'),('--x-cinnabar-58','#D46E5E'),
                 ('--x-cinnabar-44','#B64034'),('--x-cinnabar-30','#891D18')],
    'warn':     [('--x-warn-96','#FFF1D7'),('--x-warn-51','#96742F'),('--x-warn-90','#F6DFBE'),('--x-warn-74','#D1B27D'),('--x-warn-58','#AA863F'),
                 ('--x-warn-44','#826321'),('--x-warn-30','#5C4303')],
}
ROLE_L = {k: [(n, h, to_lab(to_rgb(h))[0]) for n, h in v] for k, v in ROLE.items()}

# 纯黑/纯白是设计上的端点，阶梯里没有更极端的档位，单独放行。
ENDPOINTS = {'#000000': '--x-n12', '#0d0d0d': '--x-n12', '#ffffff': '--x-n100'}

MAX_DL = 6.0

def hsl(h):
    r, g, b = to_rgb(h)
    hh, l, s = colorsys.rgb_to_hls(r/255, g/255, b/255)
    return hh*360, s, l

def classify(h):
    H, S, L = hsl(h)
    if S < 0.30:
        return 'neutral'
    if H < 20 or H >= 320:   return 'cinnabar'  # 含粉/品红：暖侧归朱砂，绝不能刷成绿
    if H < 50:               return 'warn'
    if H < 165:              return 'pine'
    return 'brand'           # 青/蓝/紫 —— 旧的 SaaS 蓝紫，归主行动色

def _nearest(pool, L):
    n, hx, tl = min(pool, key=lambda r: abs(r[2] - L))
    return n, abs(tl - L)

def _expand(h):
    h = h.lower()
    return '#' + ''.join(c * 2 for c in h[1:]) if len(h) == 4 else h

def map_color(raw):
    """返回 (token, 说明, dL) 或 None。**所有分支一律过 ΔL 闸门。**"""
    h = _expand(raw)
    if h in ENDPOINTS:
        return (ENDPOINTS[h.lower()], 'endpoint', 0.0)
    kind = classify(h)
    L = to_lab(to_rgb(h))[0]
    if kind == 'neutral':
        n, dl = _nearest(RAMP_L, L)
        return (n, 'neutral', dl) if dl <= MAX_DL else None
    if kind == 'brand':
        # 低饱和的蓝灰其实是中性，别整片刷成绿
        if hsl(h)[1] < 0.45:
            n, dl = _nearest(RAMP_L, L)
            return (n, 'brand→neutral', dl) if dl <= MAX_DL else None
        n, dl = _nearest(ROLE_L['pine'], L)
        return (n, 'brand→pine', dl) if dl <= MAX_DL else None
    n, dl = _nearest(ROLE_L[kind], L)
    return (n, kind, dl) if dl <= MAX_DL else None

def chunks(css):
    """粗切成 (选择器, 起, 止)。够用：只为判断这段要不要保护。"""
    out, depth, sel_start, body_start = [], 0, 0, None
    for i, c in enumerate(css):
        if c == '{':
            if depth == 0:
                body_start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                out.append((css[sel_start:body_start], body_start, i + 1))
                sel_start = i + 1
    return out

def run(path, apply=False):
    css = open(path, encoding='utf-8').read()
    token_end = css.index('\n}\n', css.index('--x-font-kai')) + 3  # token 块自身不动
    report, skipped, protected = [], [], 0
    pieces, last = [], 0
    for sel, b, e in chunks(css):
        if e <= token_end:
            continue
        seg = css[b:e]
        if PROTECT.search(sel):
            protected += 1
            continue
        def sub(m):
            h = m.group(0)
            r = map_color(h)
            if r is None:
                skipped.append((h, sel.strip()[:60]))
                return h
            tok, why, dl = r
            report.append((h, tok, why, dl))
            return f'var({tok})'
        new = re.sub(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b(?![0-9a-fA-F])', sub, seg)
        if new != seg:
            pieces.append((b, e, new))
    if apply:
        out, cur = [], 0
        for b, e, new in pieces:
            out.append(css[cur:b]); out.append(new); cur = e
        out.append(css[cur:])
        open(path, 'w', encoding='utf-8').write(''.join(out))
    return report, skipped, protected

if __name__ == '__main__':
    apply = '--apply' in sys.argv
    rep, skip, prot = run('src/index.css', apply)
    from collections import Counter
    print(f"可替换 {len(rep)} 处 | 跳过 {len(skip)} 处 | 受保护规则块 {prot} 个")
    print(f"最大 ΔL* = {max((r[3] for r in rep), default=0):.2f}（闸门 {MAX_DL}）")
    print("\n按去向统计：")
    for k, n in Counter(r[2] for r in rep).most_common():
        print(f"  {k:16} {n}")
    print("\n映射示例（各类前 3 条）：")
    seen = set()
    for h, tok, why, dl in rep:
        k = (why, tok)
        if k in seen: continue
        seen.add(k)
        print(f"  {h} → {tok:18} {why:16} ΔL*={dl:.1f}")
    print(f"\n跳过的（ΔL* 超闸门）前 10：")
    for h, sel in skip[:10]:
        print(f"  {h}  in  {sel}")
