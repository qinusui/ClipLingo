/**
 * ClipLingo 统一错误码映射
 *
 * 后端通过 error_code 字段传递错误码，前端根据错误码显示友好提示。
 */

export const ERROR_MESSAGES: Record<string, string> = {
  // API 相关
  API_KEY_INVALID: 'API Key 无效，请在设置中重新配置',
  API_KEY_MISSING: '请先在设置中填写 API Key',
  API_QUOTA_EXCEEDED: 'API 余额不足，请充值后重试',
  API_RATE_LIMITED: '请求太频繁，请稍后再试',
  API_TIMEOUT: 'API 请求超时，请检查网络连接',
  API_CONNECTION_FAILED: '无法连接到 API 服务器，请检查 API 地址',
  API_MODEL_NOT_FOUND: '所选模型不存在，请在设置中更换模型',

  // ffmpeg 相关
  FFMPEG_NOT_FOUND: '未检测到 ffmpeg，请确保程序完整安装',
  FFMPEG_FAILED: '媒体处理失败，视频文件可能已损坏',

  // Whisper 相关
  WHISPER_NOT_INSTALLED: 'Whisper 未安装，请在设置中安装语音识别组件',
  WHISPER_MODEL_FAILED: 'Whisper 模型加载失败，请检查网络连接',
  WHISPER_TRANSCRIBE_FAILED: '语音识别失败，请重试或手动导入字幕',
  WHISPER_TIMEOUT: '语音识别超时，请尝试使用更小的模型',

  // 字幕相关
  SUBTITLE_EMPTY: '没有符合条件的字幕，请调整筛选条件',
  SUBTITLE_PARSE_FAILED: '字幕文件格式错误，请检查文件编码',

  // AI 处理
  AI_PROCESS_FAILED: 'AI 处理失败，请检查 API 配置',

  // 通用
  INTERNAL_ERROR: '程序内部错误，请重试',
}

/**
 * 根据错误码获取友好提示
 *
 * @param errorCode - 后端返回的错误码
 * @param fallback - 无匹配时的兜底文本
 */
export function getFriendlyMessage(errorCode?: string | null, fallback?: string): string {
  if (errorCode && ERROR_MESSAGES[errorCode]) {
    return ERROR_MESSAGES[errorCode]
  }
  return fallback || '未知错误，请重试'
}

/**
 * 从 axios 错误中提取友好提示
 * 优先使用后端返回的 error_code，其次用 HTTP 状态码推断，最后用 error.message
 */
export function getApiErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const err = error as Record<string, unknown>
    // axios 错误结构
    const response = err.response as Record<string, unknown> | undefined
    if (response) {
      const data = response.data as Record<string, unknown> | undefined
      // 后端返回了 error_code
      if (data?.error_code) {
        return getFriendlyMessage(data.error_code as string, data.detail as string)
      }
      // 后端返回了 detail
      if (data?.detail) {
        return data.detail as string
      }
      // HTTP 状态码推断
      const status = response.status as number
      if (status === 401) return ERROR_MESSAGES.API_KEY_INVALID
      if (status === 429) return ERROR_MESSAGES.API_RATE_LIMITED
      if (status === 404) return '请求的资源不存在'
      if (status >= 500) return '服务器内部错误，请稍后重试'
    }
    // 网络错误
    if (err.message === 'Network Error') {
      return '网络连接失败，请检查网络'
    }
    if (typeof err.message === 'string') {
      return err.message
    }
  }
  return '未知错误，请重试'
}
