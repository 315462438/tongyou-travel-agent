/**
 * 好友分享版旅行攻略视觉规范
 * 字号、间距、配色统一定义
 */

// ===== 字号系统 =====
// OpenXML w:sz 单位是半磅（half-point），10pt = 20
export const FONT_SIZES = {
  coverTitle: 56,      // 28pt
  coverSubtitle: 28,   // 14pt
  coverMeta: 20,       // 10pt
  coverStats: 19,      // 9.5pt

  sectionTitle: 44,    // 22pt - "出发前一定要看"

  dayLabel: 22,        // 11pt - "OCT 01"
  dayTitle: 40,        // 20pt - "抵达吉隆坡 · 市区观光"
  dayRoute: 19,        // 9.5pt - 今日路线

  eventTime: 22,       // 11pt - "09:30"
  placeName: 25,       // 12.5pt - 地点名称
  eventDesc: 20,       // 10pt - 事件描述

  badge: 19,           // 9.5pt - Badge 文字

  tipTitle: 21,        // 10.5pt - 提示标题
  tipContent: 20,      // 10pt - 提示正文

  restaurantName: 25,  // 12.5pt
  restaurantMeta: 19,  // 9.5pt

  hotelName: 24,       // 12pt
  hotelMeta: 19,       // 9.5pt

  tableHeader: 19,     // 9.5pt
  tableCell: 20,       // 10pt

  body: 21,            // 10.5pt - 默认正文
  bodySmall: 20,       // 10pt
  aux: 19,             // 9.5pt - 辅助文字
  tiny: 17,            // 8.5pt
} as const

// ===== 间距系统 =====
// OpenXML w:spacing 单位是 twip，1pt = 20 twip
export const SPACING = {
  xs: 80,    // 4pt
  sm: 120,   // 6pt
  md: 160,   // 8pt
  lg: 240,   // 12pt
  xl: 320,   // 16pt
  xxl: 480,  // 24pt
  xxxl: 640, // 32pt
} as const

// ===== 配色 =====
export const COLORS = {
  // 主色
  primary: '3155C6',      // 品牌蓝
  primaryLight: 'DBEAFE', // 浅蓝背景
  primaryDark: '1E40AF',  // 深蓝

  // 中性色
  ink: '18181B',          // 标题黑
  text: '27272A',         // 正文灰
  textLight: '3F3F46',    // 浅灰
  muted: '71717A',        // 辅助灰
  mutedLight: 'A1A1AA',   // 更浅灰

  // 边框/背景
  border: 'E4E4E7',       // 边框灰
  borderLight: 'F4F4F5',  // 浅边框
  bg: 'FAFAFA',           // 卡片背景
  bgLight: 'F9FAFB',      // 更浅背景

  // 功能色
  bgWarn: 'FEF3C7',       // 警告黄背景
  bgInfo: 'DBEAFE',       // 信息蓝背景
  bgSuccess: 'D1FAE5',    // 成功绿背景

  textWarn: 'D97706',     // 警告文字
  textInfo: '2563EB',     // 信息文字
  textSuccess: '059669',  // 成功文字

  // 评分/价格
  rating: 'F59E0B',       // 评分橙
  price: '3155C6',        // 价格蓝
} as const

// ===== Badge 图标映射 =====
export const BADGE_ICONS = {
  transport: {
    taxi: '🚕',
    bus: '🚌',
    walk: '🚶',
    boat: '⛵',
    flight: '✈️',
    train: '🚆',
    default: '🚗',
  },
  duration: '⏱',
  cost: '🎫',
  location: '📍',
} as const

// ===== Tip 图标映射 =====
export const TIP_ICONS = {
  warning: '⚠️',
  info: '💡',
  photo: '📷',
  snorkel: '🤿',
  food: '🍽',
  shopping: '🛍️',
  money: '💰',
  default: '📝',
} as const

// ===== 分类图标映射 =====
export const CATEGORY_ICONS = {
  证件: '📄',
  交通: '🚗',
  安全: '🛡️',
  浮潜: '🤿',
  购物: '🛍️',
  现金: '💰',
  机场: '✈️',
  其他: '📌',
} as const
