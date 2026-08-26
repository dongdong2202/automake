/**
 * 货币金额精确转换与格式化工具模块
 * 
 * 核心规范：
 * 1. 后端与数据库：一律使用【人民币分】（整数 Integer）存储与计算。
 * 2. 前端展示与录入：一律使用【人民币元】（浮点/两位小数）呈现。
 * 3. 转换保证稳定、准确，杜绝 JS 浮点数精度截断误差（如 1.14 * 100 = 113.99999999999999）。
 */

/**
 * 分转元（数值类型，用于数值计算和 input-number 绑定）
 * @param fen 分（整数或数字字符串）
 * @returns 元（数值，保留两位有效精度）
 * @example fenToYuan(1250) => 12.5
 */
export function fenToYuan(fen: number | string | null | undefined): number {
  if (fen === null || fen === undefined || fen === '') return 0
  const num = Number(fen)
  if (isNaN(num)) return 0
  return Number((num / 100).toFixed(2))
}

/**
 * 分转元（固定两位小数字符串，用于表格/标签等文本渲染）
 * @param fen 分
 * @returns 字符串，如 "12.50"
 * @example formatFenToYuan(1250) => "12.50"
 * @example formatFenToYuan(0) => "0.00"
 */
export function formatFenToYuan(fen: number | string | null | undefined): string {
  if (fen === null || fen === undefined || fen === '') return '0.00'
  const num = Number(fen)
  if (isNaN(num)) return '0.00'
  return (num / 100).toFixed(2)
}

/**
 * 元转分（四舍五入整数，杜绝浮点数计算精度丢失）
 * @param yuan 元（如 18.5, 0.99 等）
 * @returns 分（整数）
 * @example yuanToFen(18.50) => 1850
 * @example yuanToFen(1.14) => 114
 */
export function yuanToFen(yuan: number | string | null | undefined): number {
  if (yuan === null || yuan === undefined || yuan === '') return 0
  const num = Number(yuan)
  if (isNaN(num)) return 0
  return Math.round(num * 100)
}

/**
 * 格式化人民币金额（带 ¥ 符号及千分位可选）
 * @param fen 分
 * @returns 如 "¥12.50"
 */
export function formatCurrency(fen: number | string | null | undefined): string {
  return `¥${formatFenToYuan(fen)}`
}

/**
 * 格式化元金额（输入已经是元，输出保留两位小数字符串）
 * @param yuan 元
 * @returns 如 "¥12.50"
 */
export function formatYuan(yuan: number | string | null | undefined): string {
  if (yuan === null || yuan === undefined || yuan === '') return '¥0.00'
  const num = Number(yuan)
  if (isNaN(num)) return '¥0.00'
  return `¥${num.toFixed(2)}`
}
