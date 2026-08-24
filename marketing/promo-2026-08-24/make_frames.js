const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '../..')
const OUT = path.join(__dirname, 'frames')
fs.mkdirSync(OUT, { recursive: true })

const esc = (value) => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')

const dataUri = (file, mime) => `data:${mime};base64,${fs.readFileSync(file).toString('base64')}`
const hero = dataUri(path.join(ROOT, 'frontend/src/assets/hero.png'), 'image/png')
const mountain = dataUri(path.join(ROOT, 'frontend/public/immersive/tiantangzhai-cinematic.webp'), 'image/webp')

function logo(x, y, scale = 1, color = '#6f63f6') {
  return `<g transform="translate(${x} ${y}) scale(${scale})" fill="none" stroke="${color}" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="10.5" cy="33.5" r="3.5" fill="${color}" stroke="none"/>
    <path d="M14.2 32.7c4.3-8 9.2 1.8 14.3-7 2.7-4.7 5.5-6.7 9-7.3" stroke-width="3.6"/>
    <path d="m31.7 13.8 7.8 3.6-5.4 6.8" stroke-width="3.6"/>
    <circle cx="10.5" cy="33.5" r="6.3" opacity=".3" stroke-width="1.7"/>
  </g>`
}

function defs(accent = '#6f63f6', accent2 = '#37c6b0') {
  return `<defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#f7f8ff"/><stop offset=".48" stop-color="#eef5ff"/><stop offset="1" stop-color="#f5efff"/></linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${accent}"/><stop offset="1" stop-color="${accent2}"/></linearGradient>
    <linearGradient id="glass" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ffffff" stop-opacity=".98"/><stop offset="1" stop-color="#ffffff" stop-opacity=".86"/></linearGradient>
    <filter id="shadow" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="24" stdDeviation="28" flood-color="#3f4784" flood-opacity=".16"/></filter>
    <filter id="soft"><feGaussianBlur stdDeviation="42"/></filter>
    <clipPath id="phone"><rect x="58" y="374" width="964" height="1390" rx="58"/></clipPath>
  </defs>`
}

function heading(kicker, line1, line2 = '') {
  return `<text x="72" y="98" class="kicker">${esc(kicker)}</text>
    <text x="72" y="182" class="headline">${esc(line1)}</text>
    ${line2 ? `<text x="72" y="252" class="headline">${esc(line2)}</text>` : ''}`
}

function shell(content, options = {}) {
  const { accent = '#6f63f6', accent2 = '#37c6b0', kicker = '17同游 · TRAVEL TOGETHER', title = '', title2 = '', progress = 0 } = options
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
  ${defs(accent, accent2)}
  <style>
    text{font-family:'Hiragino Sans GB','PingFang SC','Microsoft YaHei',sans-serif;fill:#182033}.kicker{font-size:25px;font-weight:700;letter-spacing:3px;fill:${accent}}.headline{font-size:58px;font-weight:800;letter-spacing:-1px}.sub{font-size:29px;fill:#687089}.label{font-size:24px;fill:#7d8498}.body{font-size:29px;fill:#273047}.strong{font-size:31px;font-weight:700}.tiny{font-size:20px;fill:#838a9d}.white{fill:#fff}.center{text-anchor:middle}
  </style>
  <rect width="1080" height="1920" fill="url(#bg)"/>
  <circle cx="95" cy="380" r="170" fill="${accent}" opacity=".08" filter="url(#soft)"/><circle cx="1010" cy="170" r="180" fill="${accent2}" opacity=".1" filter="url(#soft)"/>
  ${heading(kicker, title, title2)}
  <rect x="58" y="374" width="964" height="1390" rx="58" fill="url(#glass)" stroke="#fff" stroke-width="3" filter="url(#shadow)"/>
  <g clip-path="url(#phone)">${content}</g>
  <rect x="72" y="1827" width="936" height="8" rx="4" fill="#dfe3f2"/><rect x="72" y="1827" width="${Math.round(936 * progress)}" height="8" rx="4" fill="url(#accent)"/>
  <text x="72" y="1878" class="tiny">17tongyou</text><text x="1008" y="1878" class="tiny" text-anchor="end">一起规划，一起出发</text>
  </svg>`
}

function appHeader(title = '开始新旅程') {
  return `<rect x="58" y="374" width="964" height="112" fill="#fbfcff"/><g transform="translate(94 405)">${logo(0, 0, 1.05)}<text x="62" y="34" class="strong">17同游</text></g><text x="964" y="442" class="body" text-anchor="end">${esc(title)}</text><line x1="58" y1="486" x2="1022" y2="486" stroke="#e8ebf5"/>`
}

function nav(active = 0) {
  const items = [['✦','对话'],['⌁','同游圈'],['▣','行程'],['◇','我的']]
  return `<rect x="58" y="1636" width="964" height="128" fill="#fbfcff"/><line x1="58" y1="1636" x2="1022" y2="1636" stroke="#e3e7f3"/>${items.map((it,i)=>`<g transform="translate(${178+i*240} 1674)"><text class="strong center" fill="${i===active?'#6f63f6':'#99a0b1'}">${it[0]}</text><text y="42" class="tiny center" fill="${i===active?'#6f63f6':'#99a0b1'}">${it[1]}</text></g>`).join('')}</g>`
}

const frames = []

frames.push(shell(`<image href="${mountain}" x="58" y="374" width="964" height="1390" preserveAspectRatio="xMidYMid slice"/><rect x="58" y="374" width="964" height="1390" fill="#10152d" opacity=".46"/><rect x="118" y="506" width="290" height="52" rx="26" fill="#fff" opacity=".2"/><text x="263" y="541" class="label white center">AI 旅行共创平台</text><text x="118" y="720" class="white" font-size="84" font-weight="800">攻略很多</text><text x="118" y="820" class="white" font-size="84" font-weight="800">但旅行还是乱？</text><text x="118" y="910" class="white" font-size="34">路线、预算、同伴意见，一次理顺</text><g transform="translate(118 1280)">${logo(0,0,2,'#ffffff')}<text x="112" y="66" class="white" font-size="64" font-weight="800">17同游</text><text x="0" y="152" class="white" font-size="34">一起规划，一起出发</text></g>`, {title:'旅行攻略，',title2:'别再一个人做',progress:.125}))

frames.push(shell(`${appHeader()}<text x="108" y="570" class="label">今天想从哪里开始？</text><rect x="92" y="602" width="896" height="230" rx="34" fill="#fff" stroke="#bfc8ff" stroke-width="4"/><text x="132" y="670" class="body">国庆想和朋友去马来西亚玩 5 天，</text><text x="132" y="718" class="body">喜欢潜水，预算 8000 元，节奏轻松</text><rect x="132" y="758" width="154" height="42" rx="21" fill="#eeecff"/><text x="209" y="787" class="tiny center" fill="#6658e8">已识别需求</text><g transform="translate(92 876)"><rect width="426" height="126" rx="30" fill="#f4f6fb"/><text x="30" y="43" class="tiny">出发地</text><text x="30" y="88" class="strong">上海</text><rect x="452" width="436" height="126" rx="30" fill="#f4f6fb"/><text x="482" y="43" class="tiny">行程天数</text><text x="482" y="88" class="strong">5 天</text></g><g transform="translate(92 1024)"><rect width="426" height="126" rx="30" fill="#f4f6fb"/><text x="30" y="43" class="tiny">预算</text><text x="30" y="88" class="strong">¥ 8000</text><rect x="452" width="436" height="126" rx="30" fill="#f4f6fb"/><text x="482" y="43" class="tiny">节奏</text><text x="482" y="88" class="strong">松弛一点</text></g><rect x="92" y="1210" width="896" height="112" rx="56" fill="url(#accent)"/><text x="540" y="1280" class="strong white center">开始规划  →</text><text x="540" y="1394" class="label center">会检查路线、节奏、预算和备选方案</text>${nav(0)}`, {title:'一句话，',title2:'说清旅行需求',progress:.25}))

frames.push(shell(`${appHeader('正在规划')}<g transform="translate(540 720)"><circle r="152" fill="#7467f6" opacity=".08"/><circle r="112" fill="#45c9b0" opacity=".14"/><circle r="74" fill="url(#accent)"/><circle r="32" fill="#fff" opacity=".95"/><path d="M-18 5c20-34 42 12 68-29" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round"/><circle cx="-18" cy="5" r="8" fill="#fff"/></g><text x="540" y="942" class="strong center">正在为你整理旅行方案</text><text x="540" y="991" class="label center">已用时 00:18 · 正在匹配路线与图片</text><g transform="translate(132 1084)">${['理解需求','搜集资料','整理方案','生成内容','检查优化'].map((t,i)=>`<g transform="translate(0 ${i*94})"><circle cx="24" cy="24" r="22" fill="${i<3?'#6f63f6':'#e3e7f2'}"/><text x="24" y="32" class="tiny white center">${i<2?'✓':i===2?'3':''}</text><text x="70" y="33" class="body" font-weight="${i===2?'700':'400'}">${t}</text>${i===2?'<rect x="694" y="2" width="90" height="42" rx="21" fill="#efedff"/><text x="739" y="30" class="tiny center" fill="#6658e8">进行中</text>':''}</g>`).join('')}</g>`, {title:'不止“加载中”',title2:'每一步都看得见',progress:.375}))

frames.push(shell(`${appHeader('马来西亚 · 5天4晚')}<image href="${hero}" x="92" y="522" width="896" height="360" preserveAspectRatio="xMidYMid slice"/><rect x="92" y="522" width="896" height="360" fill="#10152d" opacity=".22"/><text x="132" y="788" class="white" font-size="48" font-weight="800">吉隆坡 + 仙本那 + 亚庇</text><text x="132" y="838" class="white" font-size="26">潜水 · 美食 · 城市漫游</text><g transform="translate(92 922)"><rect width="896" height="166" rx="30" fill="#f7f8ff"/><rect width="14" height="166" rx="7" fill="#ff6b68"/><text x="46" y="52" class="strong">DAY 1 · 抵达吉隆坡</text><text x="46" y="102" class="body">机场 → 独立广场 → 茨厂街夜市</text><text x="46" y="140" class="tiny">路线、交通、预约提醒已经排好</text><rect y="190" width="896" height="166" rx="30" fill="#f7f8ff"/><rect y="190" width="14" height="166" rx="7" fill="#38bfa9"/><text x="46" y="242" class="strong">DAY 2 · 仙本那潜水</text><text x="46" y="292" class="body">马达京 → 邦邦岛 → 海景晚餐</text><text x="46" y="330" class="tiny">预算与天气风险同步检查</text><rect y="380" width="896" height="166" rx="30" fill="#f7f8ff"/><rect y="380" width="14" height="166" rx="7" fill="#6f63f6"/><text x="46" y="432" class="strong">DAY 3 · 海岛慢生活</text><text x="46" y="482" class="body">跳岛浮潜 → 日落机位 → 海鲜市场</text></g>${nav(0)}`, {title:'图文攻略，',title2:'重点一眼看懂',progress:.5}))

frames.push(shell(`${appHeader('协同行程')}<rect x="92" y="520" width="896" height="588" rx="34" fill="#eaf2ef"/><path d="M128 760C270 650 350 930 484 780S700 608 944 748" fill="none" stroke="#ff6868" stroke-width="14" stroke-linecap="round"/><path d="M128 760C270 650 350 930 484 780S700 608 944 748" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="10 24"/><g>${[[128,760,1],[340,826,2],[484,780,3],[692,662,4],[944,748,5]].map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="33" fill="#ff6868" stroke="#fff" stroke-width="7"/><text x="${p[0]}" y="${p[1]+10}" class="body white center" font-weight="800">${p[2]}</text>`).join('')}</g><rect x="132" y="550" width="300" height="68" rx="34" fill="#fff" opacity=".94"/><text x="282" y="594" class="body center">DAY 1 · 吉隆坡</text><g transform="translate(92 1144)">${[['09:30','双子塔','已确认'],['12:00','茨厂街','同伴推荐'],['18:30','阿罗街夜市','待投票']].map((r,i)=>`<g transform="translate(0 ${i*122})"><rect width="896" height="100" rx="26" fill="#f7f8ff"/><circle cx="42" cy="50" r="18" fill="${['#ff6868','#38bfa9','#6f63f6'][i]}"/><text x="78" y="42" class="strong">${r[0]} · ${r[1]}</text><text x="78" y="76" class="tiny">${r[2]}</text><text x="846" y="61" class="body center">⋯</text></g>`).join('')}</g>${nav(2)}`, {title:'从攻略到行程',title2:'地图与日程一起改',progress:.625}))

frames.push(shell(`${appHeader('吉隆坡之旅 · 群聊')}<g transform="translate(92 538)"><text class="tiny center" x="448" y="22">今天 19:42</text><g transform="translate(0 60)"><circle cx="42" cy="42" r="42" fill="#dcd8ff"/><text x="42" y="53" class="strong center" fill="#6759e9">A</text><rect x="104" width="570" height="116" rx="28" fill="#f1f3f9"/><text x="138" y="45" class="body">第二天潜水要不要提前订？</text><text x="138" y="83" class="tiny">我担心国庆满位</text></g><g transform="translate(0 218)"><circle cx="854" cy="42" r="42" fill="#c9f0e7"/><text x="854" y="53" class="strong center" fill="#188d78">我</text><rect x="216" width="570" height="116" rx="28" fill="#6f63f6"/><text x="250" y="45" class="body white">我已经把预约提醒加进行程了</text><text x="250" y="83" class="tiny white">大家投票后我来订</text></g><g transform="translate(0 376)"><circle cx="42" cy="42" r="42" fill="#ffe2d0"/><text x="42" y="53" class="strong center" fill="#d16b2e">M</text><rect x="104" width="610" height="116" rx="28" fill="#f1f3f9"/><text x="138" y="45" class="body">那我负责整理海鲜餐厅 🍤</text><text x="138" y="83" class="tiny">顺便看看日落时间</text></g><rect x="0" y="610" width="896" height="142" rx="36" fill="#f7f8ff" stroke="#e2e6f2"/><text x="42" y="693" class="label">和同伴聊聊行程细节…</text><circle cx="826" cy="681" r="42" fill="url(#accent)"/><path d="M811 681h30m-10-10 10 10-10 10" stroke="#fff" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/><g transform="translate(0 804)"><rect width="896" height="170" rx="30" fill="#f0edff"/><text x="38" y="52" class="strong" fill="#6658e8">沟通不再散落</text><text x="38" y="103" class="body">群聊贴着行程走，地点留言也保留</text><text x="38" y="142" class="tiny">谁改了路线、谁负责预订，一目了然</text></g></g>${nav(2)}`, {title:'不是各做各的',title2:'群聊让同伴真正参与',progress:.75}))

frames.push(shell(`${appHeader('同游圈 · 目的地接力站')}<image href="${mountain}" x="92" y="522" width="896" height="330" preserveAspectRatio="xMidYMid slice"/><rect x="92" y="522" width="896" height="330" fill="#121831" opacity=".24"/><rect x="126" y="558" width="230" height="48" rx="24" fill="#fff" opacity=".9"/><text x="241" y="590" class="tiny center" fill="#6658e8">72 小时现场情报</text><text x="126" y="770" class="white" font-size="50" font-weight="800">天堂寨 · 旅行接力</text><g transform="translate(92 900)"><rect width="896" height="190" rx="32" fill="#f7f8ff"/><circle cx="66" cy="64" r="40" fill="#d9f3ed"/><text x="66" y="75" class="strong center" fill="#208d79">山</text><text x="126" y="54" class="strong">正在玩 · 2小时前</text><text x="126" y="100" class="body">峡谷步道水汽大，鞋底要防滑</text><rect x="126" y="126" width="156" height="40" rx="20" fill="#e8f6f2"/><text x="204" y="153" class="tiny center" fill="#208d79">✓ 已验证 12</text><rect y="218" width="896" height="190" rx="32" fill="#f7f8ff"/><circle cx="66" cy="282" r="40" fill="#ece9ff"/><text x="66" y="293" class="strong center" fill="#6658e8">旅</text><text x="126" y="272" class="strong">刚回来 · 路线分享</text><text x="126" y="318" class="body">白马峡谷 → 哲人峰，轻松版 6 小时</text><rect x="126" y="344" width="156" height="40" rx="20" fill="#efedff"/><text x="204" y="371" class="tiny center" fill="#6658e8">有用 28</text><rect y="436" width="896" height="150" rx="32" fill="#f7f8ff"/><text x="42" y="496" class="strong">你的经验，也能成为下一站答案</text><text x="42" y="540" class="tiny">准备去 · 正在玩 · 刚回来</text></g>${nav(1)}`, {title:'真实旅行情报',title2:'一程接一程',progress:.875}))

frames.push(shell(`<image href="${hero}" x="58" y="374" width="964" height="1390" preserveAspectRatio="xMidYMid slice"/><rect x="58" y="374" width="964" height="1390" fill="#11152f" opacity=".63"/><g transform="translate(540 720)"><circle r="132" fill="#fff" opacity=".13"/><g transform="translate(-68 -68)">${logo(0,0,3,'#ffffff')}</g></g><text x="540" y="980" class="white center" font-size="92" font-weight="800">17同游</text><text x="540" y="1060" class="white center" font-size="38">一起规划，一起出发</text><rect x="260" y="1160" width="560" height="104" rx="52" fill="#fff"/><text x="540" y="1227" class="strong center" fill="#6658e8">现在开始你的下一程  →</text><text x="540" y="1355" class="white center" font-size="30">17tongyou</text>`, {title:'下一次出发，',title2:'从 17同游 开始',progress:1}))

frames.forEach((svg, index) => fs.writeFileSync(path.join(OUT, `${String(index + 1).padStart(2, '0')}.svg`), svg))
fs.writeFileSync(path.join(OUT, 'contact-sheet.html'), `<!doctype html><html><head><meta charset="utf-8"><style>*{box-sizing:border-box}html,body{margin:0;width:8640px;height:1920px;overflow:hidden;background:#fff}body{display:flex}img{display:block;width:1080px;height:1920px;flex:none}</style></head><body>${frames.map((_, index) => `<img src="${String(index + 1).padStart(2, '0')}.svg">`).join('')}</body></html>`)
console.log(`Generated ${frames.length} SVG frames in ${OUT}`)
