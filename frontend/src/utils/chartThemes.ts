/**
 * chartThemes.ts
 *
 * 工业级现代化数据可视化通用配置与主题工具模块
 * 遵循现代企业级商业智能（BI）大盘设计规范：
 * 1. 采用高对比、柔和微渐变色系（深蓝、翡翠绿、琥珀橙、珊瑚紫等）；
 * 2. 统一毛玻璃半透明 Tooltip 交互与平滑贝塞尔曲线（smooth: 0.35）；
 * 3. 规范响应式网格（Grid）与数据标签布局。
 */

import * as echarts from 'echarts'

/**
 * 现代化商业可视化标准色板（Palette）
 */
export const CHART_COLORS = {
  // 主色调：科技蓝与深邃青
  primary: '#3b82f6',
  primaryLight: '#60a5fa',
  primarySoft: 'rgba(59, 130, 246, 0.15)',

  // 成功/正向/营收：翡翠绿
  success: '#10b981',
  successLight: '#34d399',
  successSoft: 'rgba(16, 185, 129, 0.15)',

  // 警告/客单均价/高峰：琥珀金橙
  warning: '#f59e0b',
  warningLight: '#fbbf24',
  warningSoft: 'rgba(245, 158, 11, 0.15)',

  // 告警/异常/故障：珊瑚红
  danger: '#ef4444',
  dangerLight: '#f87171',
  dangerSoft: 'rgba(239, 68, 68, 0.15)',

  // 特色/特调/转化：极光紫与粉红
  purple: '#8b5cf6',
  purpleLight: '#a78bfa',
  purpleSoft: 'rgba(139, 92, 246, 0.15)',

  // 中性灰：用于背景轴线与文字
  textPrimary: '#1e293b',
  textSecondary: '#64748b',
  textMuted: '#94a3b8',
  borderLight: '#e2e8f0',
  gridLine: '#f1f5f9',

  // 常用双色渐变对
  blueGrad: ['#3b82f6', '#60a5fa'] as const,
  greenGrad: ['#10b981', '#34d399'] as const,
  orangeGrad: ['#f59e0b', '#fbbf24'] as const,
  purpleGrad: ['#8b5cf6', '#a78bfa'] as const,

  // 经典多序列企业级明亮色板
  palette: ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899', '#f97316', '#6366f1'],
}

/**
 * 生成垂直方向或水平方向的双色线性渐变
 * @param colorStart 起始颜色
 * @param colorEnd 终止颜色
 * @param isVertical 是否为垂直方向（默认 true：上到下；false：左到右）
 */
export function createLinearGradient(colorStart: string, colorEnd: string, isVertical = true) {
  return new echarts.graphic.LinearGradient(
    0,
    0,
    isVertical ? 0 : 1,
    isVertical ? 1 : 0,
    [
      { offset: 0, color: colorStart },
      { offset: 1, color: colorEnd },
    ]
  )
}

/**
 * 工业级毛玻璃悬浮窗（Tooltip）统一配置
 */
export const MODERN_TOOLTIP = {
  trigger: 'axis' as const,
  backgroundColor: 'rgba(255, 255, 255, 0.95)',
  borderColor: '#e2e8f0',
  borderWidth: 1,
  padding: [10, 14],
  textStyle: {
    color: '#1e293b',
    fontSize: 12,
  },
  extraCssText:
    'box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.04); backdrop-filter: blur(8px); border-radius: 8px;',
}

/**
 * 饼图/环形图专用的毛玻璃悬浮窗
 */
export const MODERN_ITEM_TOOLTIP = {
  ...MODERN_TOOLTIP,
  trigger: 'item' as const,
}

/**
 * 统一网格（Grid）配置：预留合理的留白，保证轴标签不截断
 */
export const MODERN_GRID = {
  left: '3%',
  right: '4%',
  bottom: '8%',
  top: '10%',
  containLabel: true,
}
