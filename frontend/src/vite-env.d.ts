/// <reference types="vite/client" />

/** 本项目自定义的构建期环境变量。真值见 `frontend/.env.local`（不进版本库），
 *  说明与申请方式见 `frontend/.env.example`。 */
interface ImportMetaEnv {
  /** 高德 Web端(JS API) key。缺失时互动地图回退静态图（TripMap 会打 console.error）。 */
  readonly VITE_AMAP_JS_KEY?: string
  /** 高德安全密钥，**仅本地开发**注入；生产由 nginx `_AMapService` 代理注入 jscode。 */
  readonly VITE_AMAP_JS_SECURITY_CODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
