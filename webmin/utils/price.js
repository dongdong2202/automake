/**
 * 价格与金额工具类
 * 后台统一使用分 (Fen, 整数)
 * 前端展示统一使用元 (Yuan, 保留2位小数)
 */

/**
 * 分转元字符串 (例如 1800 -> "18.00")
 * @param {number} fen 金额（分）
 * @param {boolean} withSymbol 是否带人民币符号 ¥
 * @returns {string}
 */
function fenToYuan(fen, withSymbol = false) {
  if (fen === null || fen === undefined || isNaN(fen)) {
    return withSymbol ? '¥0.00' : '0.00'
  }
  const yuan = (Number(fen) / 100).toFixed(2)
  return withSymbol ? `¥${yuan}` : yuan
}

/**
 * 元转分整数 (例如 18.5 -> 1850)
 * @param {number|string} yuan 金额（元）
 * @returns {number}
 */
function yuanToFen(yuan) {
  if (yuan === null || yuan === undefined || isNaN(yuan)) {
    return 0
  }
  return Math.round(Number(yuan) * 100)
}

/**
 * 计算商品最终单价 (基础价格 + 所选各 SKU 价格增量)
 * @param {number} basePrice 基础价格（分）
 * @param {Array} selectedSkus 所选规格对象数组 [{ price_delta: 300 }, ...]
 * @returns {number} 最终单价（分）
 */
function calculateUnitPrice(basePrice, selectedSkus = []) {
  let total = Number(basePrice) || 0
  if (Array.isArray(selectedSkus)) {
    selectedSkus.forEach(sku => {
      if (sku && typeof sku.price_delta === 'number') {
        total += sku.price_delta
      }
    })
  }
  return total
}

module.exports = {
  fenToYuan,
  yuanToFen,
  calculateUnitPrice
}
