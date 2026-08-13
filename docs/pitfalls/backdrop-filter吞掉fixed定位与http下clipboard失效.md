# 两个前端坑：backdrop-filter 吞掉 fixed 定位 / http 下 clipboard 静默失效

## 坑一：弹窗渲染在带 backdrop-filter 的祖先里，fixed 全屏遮罩变成局部

**现象**：分享弹窗贴在页面顶部、遮罩没有盖住全屏，地图完全可见（Phase 42.2）。

**原因**：CSS 规范规定 `filter` / `backdrop-filter` / `transform` 等属性会让元素成为
后代 **fixed 定位元素的 containing block**——弹窗组件渲染在板头（`.trip-board-head`
有 `backdrop-filter: blur(8px)` 毛玻璃）内部，它的 `position: fixed; inset: 0`
遮罩就变成了「相对板头那一条」而不是相对视口。

**解决**：弹窗用 `createPortal(<Modal/>, document.body)` 挂到 body，彻底脱离
毛玻璃祖先。**规则：任何全屏 modal 都应 portal 到 body**，尤其项目里毛玻璃
（backdrop-filter）用得多的界面。

## 坑二：http（IP 访问）下 navigator.clipboard 不存在，可选链让复制静默失败

**现象**：用户点「复制微信文案」，粘贴出来是**上一次截的图**——看起来像功能复制了
个截图，实际是什么都没复制、剪贴板还是旧内容。

**原因**：Clipboard API 只在 **secure context**（https / localhost）暴露；
线上是 `http://IP`，`navigator.clipboard` 为 undefined，代码里
`navigator.clipboard?.writeText(...)` 的可选链**静默跳过**，无报错无提示。

**解决**：`copyText()` 降级——clipboard 不存在时用隐藏 textarea +
`document.execCommand('copy')`（http 下可用）。**规则：凡「复制」功能必须带
execCommand 降级，或至少失败要提示**；等站点上 https 后 clipboard 自然恢复，
降级代码保留无害。
