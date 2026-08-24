"""行记调色板 + CIEDE2000 距离。批量替换的安全网就在 delta_e 上。"""
import math, re

TOKENS = {
    # 纸阶
    '--x-paper':        '#F7F3EA',
    '--x-paper-raised': '#FFFEFB',
    '--x-paper-sunken': '#F1EEE4',
    # 墨阶
    '--x-ink':          '#241F1B',
    '--x-ink-2':        '#6A6046',
    '--x-ink-3':        '#9C8F6F',
    # 线
    '--x-line':         '#CDBF9C',
    '--x-line-soft':    '#E3DCC7',
    # 角色色
    '--x-pine':         '#3F6B52',
    '--x-pine-strong':  '#2C4C39',
    '--x-pine-soft':    '#E8EFE9',
    '--x-cinnabar':     '#B23A2F',
    '--x-cinnabar-soft':'#F6E7E3',
    # 语义
    '--x-success':      '#3F6B52',
    '--x-warn':         '#A8843C',
    '--x-danger':       '#B23A2F',
    # 日序
    '--x-day-1': '#C2603E', '--x-day-2': '#3F6B52', '--x-day-3': '#3C6E8F',
    '--x-day-4': '#8A5A9B', '--x-day-5': '#A8843C', '--x-day-6': '#5C6B7A',
    # 纯白/纯黑保留位（阴影与图片底用）
    '--x-white': '#FFFFFF',
}

def to_rgb(h):
    h = h.lstrip('#').lower()
    if len(h) == 3: h = ''.join(c*2 for c in h)
    if len(h) == 4: h = ''.join(c*2 for c in h[:3])
    if len(h) == 8: h = h[:6]
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def to_lab(rgb):
    def f(c):
        c /= 255
        return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    x = (0.4124*r + 0.3576*g + 0.1805*b) / 0.95047
    y = (0.2126*r + 0.7152*g + 0.0722*b)
    z = (0.0193*r + 0.1192*g + 0.9505*b) / 1.08883
    def g_(t): return t ** (1/3) if t > 0.008856 else 7.787*t + 16/116
    fx, fy, fz = g_(x), g_(y), g_(z)
    return 116*fy - 16, 500*(fx-fy), 200*(fy-fz)

def delta_e(h1, h2):
    """CIEDE2000。"""
    L1, a1, b1 = to_lab(to_rgb(h1)); L2, a2, b2 = to_lab(to_rgb(h2))
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb**7 / (Cb**7 + 25**7))) if Cb > 0 else 0
    a1p, a2p = (1+G)*a1, (1+G)*a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0
    dLp, dCp = L2-L1, C2p-C1p
    if C1p*C2p == 0: dhp = 0
    elif abs(h2p-h1p) <= 180: dhp = h2p-h1p
    elif h2p-h1p > 180: dhp = h2p-h1p-360
    else: dhp = h2p-h1p+360
    dHp = 2*math.sqrt(C1p*C2p)*math.sin(math.radians(dhp)/2)
    Lbp, Cbp = (L1+L2)/2, (C1p+C2p)/2
    if C1p*C2p == 0: hbp = h1p+h2p
    elif abs(h1p-h2p) <= 180: hbp = (h1p+h2p)/2
    elif h1p+h2p < 360: hbp = (h1p+h2p+360)/2
    else: hbp = (h1p+h2p-360)/2
    T = (1 - 0.17*math.cos(math.radians(hbp-30)) + 0.24*math.cos(math.radians(2*hbp))
         + 0.32*math.cos(math.radians(3*hbp+6)) - 0.20*math.cos(math.radians(4*hbp-63)))
    Sl = 1 + (0.015*(Lbp-50)**2)/math.sqrt(20+(Lbp-50)**2)
    Sc, Sh = 1 + 0.045*Cbp, 1 + 0.015*Cbp*T
    Rt = -2*math.sqrt(Cbp**7/(Cbp**7+25**7))*math.sin(math.radians(60*math.exp(-((hbp-275)/25)**2))) if Cbp > 0 else 0
    return math.sqrt((dLp/Sl)**2 + (dCp/Sc)**2 + (dHp/Sh)**2 + Rt*(dCp/Sc)*(dHp/Sh))

def nearest(hexv, pool=None):
    pool = pool or TOKENS
    best = min(pool.items(), key=lambda kv: delta_e(hexv, kv[1]))
    return best[0], best[1], delta_e(hexv, best[1])
