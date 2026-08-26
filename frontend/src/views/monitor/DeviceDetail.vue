<template>
  <div class="page-container device-detail-page">
    <PageHeader
      :title="`设备详情与监控：${deviceInfo.device_name || sn}`"
      :subtitle="`序列号：${sn} | 所属门店：${deviceInfo.store_name || '-'}`"
    >
      <template #actions>
        <el-button icon="Back" @click="$router.push('/monitor')">返回大屏</el-button>
        <el-button type="primary" icon="Refresh" @click="fetchDetail">刷新状态</el-button>
      </template>
    </PageHeader>

    <!-- 🚨 专属健康问题与异常编号诊断面板 (只提取展示有问题的编号) -->
    <div v-if="problematicItems.length > 0" class="problem-diagnosis-card">
      <div class="problem-header">
        <div class="header-left">
          <el-icon class="alert-icon" color="#F56C6C"><WarningFilled /></el-icon>
          <span class="problem-title">
            检测到 <strong>{{ problematicItems.length }}</strong> 项设备健康问题（已仅提取有问题的编号）：
          </span>
        </div>
        <el-button
          type="danger"
          size="small"
          plain
          @click="barrelFilterMode = 'problem_only'"
        >
          在图表中仅看问题桶
        </el-button>
      </div>
      <div class="problem-tags-container">
        <el-tag
          v-for="prob in problematicItems"
          :key="prob.id"
          :type="prob.type"
          size="large"
          effect="dark"
          class="problem-badge"
        >
          <span class="prob-cat">{{ prob.category }}:</span>
          <strong class="prob-code">{{ prob.label }}</strong>
          <span class="prob-desc">【{{ prob.detail }}】</span>
        </el-tag>
      </div>
    </div>
    <div v-else class="healthy-diagnosis-card">
      <el-icon color="#67C23A"><CircleCheckFilled /></el-icon>
      <span>整机健康状况良好，所有 37 个料桶及 8 大执行机构均无故障异常。</span>
    </div>

    <el-tabs v-model="activeTab" class="detail-tabs">
      <!-- Tab 1: 实时运行状态与料桶 -->
      <el-tab-pane label="实时监控与料桶" name="realtime">
        <!-- 核心指标卡片 -->
        <el-row :gutter="16" class="kpi-row">
          <el-col :xs="24" :sm="8">
            <div class="kpi-card">
              <div class="kpi-title">
                <span>整机健康状况</span>
              </div>
              <div class="kpi-value">
                <StatusBadge
                  :status="snapshot.display_status || (snapshot.healthy ? 'normal' : 'fault')"
                  :text="snapshot.display_status === 'normal' ? '健康运行' : '存在异常'"
                />
              </div>
              <div class="kpi-footer">
                <span>最后上报：{{ snapshot.reported_at ? formatTime(snapshot.reported_at) : '暂无' }}</span>
              </div>
            </div>
          </el-col>

          <el-col :xs="24" :sm="8">
            <div class="kpi-card">
              <div class="kpi-title">
                <span>冷柜与加热温度</span>
              </div>
              <div class="kpi-value">
                冷柜 {{ snapshot.temperature?.t1 ?? '-' }}°C / 加热 {{ snapshot.temperature?.t2 ?? '-' }}°C
              </div>
              <div class="kpi-footer">
                <span>上位机内存：{{ snapshot.free?.master ?? '-' }}MB / 下位机：{{ snapshot.free?.slave ?? '-' }}KB</span>
              </div>
            </div>
          </el-col>

          <el-col :xs="24" :sm="8">
            <div class="kpi-card">
              <div class="kpi-title">
                <span>耗材与料桶总览</span>
              </div>
              <div class="kpi-value">
                大纸杯 {{ snapshot.cups?.paperL?.damaged ? '损坏' : (snapshot.cups?.paperL?.empty ? '缺杯' : '正常') }} /
                料桶 {{ allBarrelsList.length }} 桶
              </div>
              <div class="kpi-footer">
                <span :style="{ color: problemBarrelCount > 0 ? '#F56C6C' : '#67C23A' }">
                  异常料桶：{{ problemBarrelCount }} 个
                </span>
              </div>
            </div>
          </el-col>
        </el-row>

        <!-- 37料桶余量柱状图 -->
        <div class="chart-card">
          <div class="card-header chart-header-flex">
            <span class="card-title">
              <el-icon><Box /></el-icon>
              所有料桶实时容量监控 (ml)
              <span class="sub-tip">（X轴展示：桶编号 + 物料名称）</span>
            </span>

            <div class="chart-filters">
              <el-radio-group v-model="barrelFilterMode" size="small">
                <el-radio-button value="all">全部 ({{ allBarrelsList.length }}桶)</el-radio-button>
                <el-radio-button value="problem_only" :disabled="problemBarrelCount === 0">
                  <span style="color: #f56c6c;">仅看异常桶 ({{ problemBarrelCount }})</span>
                </el-radio-button>
                <el-radio-button value="thin">薄料区 (b01~b08)</el-radio-button>
                <el-radio-button value="thick">浆料区 (b09~b31)</el-radio-button>
                <el-radio-button value="solid">固料区 (b32~b37)</el-radio-button>
              </el-radio-group>
            </div>
          </div>

          <div class="chart-legend-custom">
            <span class="legend-item"><i class="dot normal"></i> 正常运行</span>
            <span class="legend-item"><i class="dot danger"></i> 模块硬件损坏 (a1=1)</span>
            <span class="legend-item"><i class="dot warning"></i> 缺料/余量耗尽 (0ml)</span>
          </div>

          <BaseChart :option="barrelChartOption" height="360px" />
        </div>

        <!-- 传感器与硬件状态 -->
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Cpu /></el-icon>
              各执行机构与传感器状态矩阵
            </span>
          </div>

          <el-descriptions :column="4" border size="default">
            <el-descriptions-item label="转运机构 (transfer)">
              <el-tag :type="snapshot.abnormalities?.['transfer.a1'] ? 'danger' : 'success'" size="small">
                {{ snapshot.abnormalities?.['transfer.a1'] ? '转运损坏' : '正常' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="制冰机 (ice)">
              <el-tag :type="hasIceProblem ? 'danger' : 'success'" size="small">
                {{ iceProblemText }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="落杯器 (cup)">
              <el-tag :type="hasCupProblem ? 'danger' : 'success'" size="small">
                {{ cupProblemText }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="机械臂 (arm)">
              <el-tag :type="snapshot.abnormalities?.['arm.a1'] ? 'danger' : 'success'" size="small">
                {{ snapshot.abnormalities?.['arm.a1'] ? '机械臂损坏' : '正常' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="压粉机构 (press)">
              <el-tag :type="snapshot.abnormalities?.['press.a1'] ? 'danger' : 'success'" size="small">
                {{ snapshot.abnormalities?.['press.a1'] ? '压盖损坏' : '正常' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="加热模块 (heat)">
              <el-tag :type="hasHeatProblem ? 'danger' : 'success'" size="small">
                {{ heatProblemText }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="取餐口 (take)">
              <el-tag :type="hasTakeProblem ? 'danger' : 'success'" size="small">
                {{ takeProblemText }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="小票打印机 (ticket)">
              <el-tag :type="hasTicketProblem ? 'danger' : 'success'" size="small">
                {{ ticketProblemText }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </el-tab-pane>

      <!-- Tab 2: 料桶字典映射 -->
      <el-tab-pane label="料桶物料字典映射" name="barrels">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">料桶字典绑定</span>
            <el-button type="primary" size="small" @click="openBindDialog">
              + 绑定新料桶
            </el-button>
          </div>

          <el-table :data="barrelsList" stripe style="width: 100%">
            <el-table-column prop="barrel_code" label="桶编号 (如 b01)" width="160">
              <template #default="{ row }">
                <el-tag size="small" type="primary" effect="plain" style="font-family: monospace; font-size: 13px;">
                  {{ row.barrel_code }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="material_name" label="对应物料名称" min-width="180" />
            <el-table-column prop="material" label="物料编码" width="150">
              <template #default="{ row }">
                <span style="font-family: monospace;">{{ row.material }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="material_type" label="物料类别" width="130">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.material_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="绑定时间" width="180" />
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-popconfirm title="确定解除该料桶映射吗？" @confirm="handleUnbindBarrel(row.id)">
                  <template #reference>
                    <el-button type="danger" link size="small">解除映射</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 绑定料桶对话框 -->
    <el-dialog v-model="showBindDialog" title="绑定设备料桶字典映射" width="500px">
      <el-form :model="bindForm" label-width="100px">
        <el-form-item label="料桶编号" required>
          <el-input v-model="bindForm.barrel_code" placeholder="上位机料桶编号，例如 b01, b02, b09" />
        </el-form-item>
        <el-form-item label="对应物料" required>
          <el-select
            v-model="bindForm.material_code"
            placeholder="请选择仓库物料"
            filterable
            style="width: 100%;"
          >
            <el-option
              v-for="m in materialOptions"
              :key="m.code"
              :label="`${m.name} (${m.code}) - ${m.material_type}`"
              :value="m.code"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBindDialog = false">取消</el-button>
        <el-button type="primary" :loading="bindLoading" @click="handleBindBarrel">
          保存映射
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Box, Cpu, Back, Refresh, WarningFilled, CircleCheckFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  getDeviceDetailApi,
  getDeviceBarrelsApi,
  bindDeviceBarrelApi,
  deleteBarrelDictApi,
} from '@/api/devices'
import { getMaterialsApi } from '@/api/inventory'
import { getMonitorDeviceDetailApi } from '@/api/monitor'
import { useWebSocket } from '@/composables/useWebSocket'

const route = useRoute()
const sn = computed(() => route.params.sn as string)

const activeTab = ref('realtime')
const deviceInfo = ref<any>({})
const snapshot = ref<any>({})
const barrelsList = ref<any[]>([])
const materialOptions = ref<any[]>([])

// 实时 WebSocket 连接与数据更新
const { isConnected: wsConnected } = useWebSocket('/ws/monitor/', (payload) => {
  if (payload && payload.device_sn === sn.value) {
    snapshot.value = {
      ...snapshot.value,
      ...payload,
      reported_at: payload.reported_at || new Date().toISOString(),
    }
  }
})

const barrelFilterMode = ref<'all' | 'problem_only' | 'thin' | 'thick' | 'solid'>('all')

const showBindDialog = ref(false)
const bindLoading = ref(false)
const bindForm = ref({
  barrel_code: '',
  material_code: '',
})

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch {
    return iso
  }
}

// 整理所有 37 个料桶的结构化列表
const allBarrelsList = computed(() => {
  const barrelsMap = snapshot.value.barrels || {}
  const rawData = snapshot.value.raw_data || {}
  
  // 建立 1~37 的桶列表
  const results: any[] = []

  for (let i = 1; i <= 37; i++) {
    const code = `b${i < 10 ? '0' + i : i}`
    let section = 'thinP'
    let sectionCn = '薄料区'
    if (i >= 9 && i <= 31) {
      section = 'thickP'
      sectionCn = '浆料区'
    } else if (i >= 32) {
      section = 'solidP'
      sectionCn = '固料区'
    }

    const bData = barrelsMap[code]
    let vol = 0
    let damaged = false
    let matName = ''
    let matCode = ''

    if (bData) {
      vol = Number(bData.volume) || 0
      damaged = Boolean(bData.damaged)
      matName = (bData.material_name && bData.material_name !== code) ? bData.material_name : ''
      matCode = bData.material_code || ''
    } else {
      // 备用从 raw_data 读取
      const secData = rawData[section] || {}
      const rawB = secData[code] || {}
      vol = Number(rawB.v) || 0
      damaged = (rawB.a1 === 1)
    }

    // 检查字典绑定（双重兜底）
    if (!matName) {
      const matchDict = barrelsList.value.find((d: any) => d.barrel_code === code)
      if (matchDict && matchDict.material_name) {
        matName = matchDict.material_name
        matCode = matchDict.material
      }
    }

    results.push({
      barrel_code: code,
      num: i,
      section,
      sectionCn,
      volume: vol,
      damaged,
      material_name: matName,
      material_code: matCode,
      displayName: matName ? `${code} (${matName})` : `${code} (未绑定)`,
      is_empty: vol <= 0,
      has_problem: damaged || vol <= 0,
    })
  }

  return results
})

// 仅有问题的料桶数量
const problemBarrelCount = computed(() => {
  return allBarrelsList.value.filter(b => b.has_problem).length
})

// 🚨 核心：仅提取所有存在健康问题的编号（料桶、耗材、执行机构、通信）
const problematicItems = computed(() => {
  const list: any[] = []

  // 1. 异常料桶编号 (损坏 a1=1 或 缺料 v<=0)
  allBarrelsList.value.forEach(b => {
    if (b.damaged) {
      list.push({
        id: `barrel.${b.barrel_code}.damaged`,
        category: '料桶硬件',
        label: b.displayName,
        code: b.barrel_code,
        type: 'danger',
        detail: `模块损坏 (当前容量: ${b.volume}ml)`
      })
    } else if (b.is_empty && b.material_name) {
      list.push({
        id: `barrel.${b.barrel_code}.empty`,
        category: '料桶物料',
        label: b.displayName,
        code: b.barrel_code,
        type: 'warning',
        detail: `物料已耗尽 (0ml)`
      })
    }
  })

  // 2. 耗材落杯器与杯盖
  const cups = snapshot.value.cups || {}
  Object.keys(cups).forEach(cKey => {
    const c = cups[cKey]
    if (c?.damaged) {
      list.push({
        id: `cup.${cKey}.damaged`,
        category: '耗材机构',
        label: `落杯/耗材 ${cKey}`,
        code: `cup.${cKey}`,
        type: 'danger',
        detail: '落杯模块硬件损坏'
      })
    }
    if (c?.empty) {
      list.push({
        id: `cup.${cKey}.empty`,
        category: '耗材余量',
        label: `耗材 ${cKey}`,
        code: `cup.${cKey}`,
        type: 'warning',
        detail: '耗材已用尽缺货'
      })
    }
  })

  // 3. 执行机构与传感器
  const abnormalities = snapshot.value.abnormalities || {}
  Object.entries(abnormalities).forEach(([k, desc]: [string, any]) => {
    if (k.startsWith('thinP.') || k.startsWith('thickP.') || k.startsWith('solidP.') || k.startsWith('cup.')) {
      // 已经由上面处理
      return
    }
    if (k === 'disconnected') {
      list.push({
        id: 'disconnected',
        category: '通信状态',
        label: '整机在线状态',
        code: 'disconnected',
        type: 'danger',
        detail: '设备已离线断开连接'
      })
    } else if (k === 'healthy') {
      // 仅当没有更具体的错误时展示
      if (list.length === 0) {
        list.push({
          id: 'healthy',
          category: '整机状态',
          label: '整机健康',
          code: 'healthy',
          type: 'danger',
          detail: '整机健康标记为异常'
        })
      }
    } else {
      list.push({
        id: k,
        category: '执行机构',
        label: k,
        code: k,
        type: 'danger',
        detail: desc || '机构运转故障'
      })
    }
  })

  return list
})

// 执行机构辅助状态文本
const hasIceProblem = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  return Boolean(ab['ice.a1'] || ab['ice.a2'] || ab['ice.a3'])
})
const iceProblemText = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  if (ab['ice.a1']) return '出口异常'
  if (ab['ice.a2']) return '制冰区异常'
  if (ab['ice.a3']) return '容器缺冰'
  return '正常'
})

const hasCupProblem = computed(() => {
  const cups = snapshot.value.cups || {}
  return Object.values(cups).some((c: any) => c?.damaged || c?.empty)
})
const cupProblemText = computed(() => {
  const cups = snapshot.value.cups || {}
  const dList: string[] = []
  Object.entries(cups).forEach(([k, v]: [string, any]) => {
    if (v?.damaged) dList.push(`${k}损坏`)
    else if (v?.empty) dList.push(`${k}缺杯`)
  })
  return dList.length > 0 ? dList.join(', ') : '正常'
})

const hasHeatProblem = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  return Boolean(ab['heat.a1'] || ab['heat.a2'] || ab['heat.a3'])
})
const heatProblemText = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  if (ab['heat.a1']) return '水加热故障'
  if (ab['heat.a2']) return '奶加热故障'
  if (ab['heat.a3']) return '茶加热故障'
  return '正常'
})

const hasTakeProblem = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  return Boolean(ab['take.a1'] || ab['take.a2'] || ab['take.a3'])
})
const takeProblemText = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  if (ab['take.a1'] || ab['take.a2'] || ab['take.a3']) return '取餐口异常'
  return '正常'
})

const hasTicketProblem = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  return Boolean(ab['ticket.a1'] || ab['ticket.a2'] || ab['ticket.a3'] || ab['ticket.a4'] || ab['ticket.a5'])
})
const ticketProblemText = computed(() => {
  const ab = snapshot.value.abnormalities || {}
  if (ab['ticket.a1']) return '打印机掉线'
  if (ab['ticket.a2']) return '打印机缺纸'
  if (ab['ticket.a3']) return '打印机过热'
  if (ab['ticket.a4']) return '切刀出错'
  if (ab['ticket.a5']) return '打印机错误'
  return '正常'
})

// 过滤后的料桶列表
const filteredBarrels = computed(() => {
  const mode = barrelFilterMode.value
  if (mode === 'problem_only') {
    return allBarrelsList.value.filter(b => b.has_problem)
  }
  if (mode === 'thin') {
    return allBarrelsList.value.filter(b => b.section === 'thinP')
  }
  if (mode === 'thick') {
    return allBarrelsList.value.filter(b => b.section === 'thickP')
  }
  if (mode === 'solid') {
    return allBarrelsList.value.filter(b => b.section === 'solidP')
  }
  return allBarrelsList.value
})

// 37料桶柱状图 Option
const barrelChartOption = computed(() => {
  const list = filteredBarrels.value
  const xLabels = list.map(b => b.displayName)
  
  const seriesData = list.map(b => {
    let barColor = '#409EFF'
    if (b.damaged) {
      barColor = '#F56C6C' // 硬件损坏: 红色
    } else if (b.volume <= 0) {
      barColor = '#E6A23C' // 缺料: 橙色
    }

    return {
      value: b.volume,
      itemStyle: {
        color: barColor,
        borderRadius: [4, 4, 0, 0],
      },
      rawInfo: b,
    }
  })

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        if (!params || params.length === 0) return ''
        const item = params[0]
        const raw = item.data?.rawInfo
        if (!raw) return `${item.name}: ${item.value} ml`
        
        let statusBadge = '<span style="color:#67C23A;">● 正常运行</span>'
        if (raw.damaged) {
          statusBadge = '<span style="color:#F56C6C;font-weight:bold;">● 模块硬件损坏 (a1=1)</span>'
        } else if (raw.volume <= 0) {
          statusBadge = '<span style="color:#E6A23C;font-weight:bold;">● 缺料/已耗尽</span>'
        }

        return `
          <div style="font-size:13px;line-height:1.6;min-width:180px;">
            <div style="font-weight:bold;margin-bottom:4px;border-bottom:1px solid #eee;padding-bottom:2px;">
              ${raw.barrel_code} - ${raw.material_name || '未绑定物料'}
            </div>
            <div>所属分区：${raw.sectionCn} (${raw.section})</div>
            <div>物料编码：${raw.material_code || '-'}</div>
            <div>实时容量：<strong>${raw.volume} ml</strong></div>
            <div>健康状态：${statusBadge}</div>
          </div>
        `
      },
    },
    grid: { left: '3%', right: '4%', bottom: '16%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xLabels.length > 0 ? xLabels : ['暂无料桶数据'],
      axisLabel: {
        rotate: 35,
        interval: 0,
        fontSize: 11,
        color: '#606266',
      },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      name: '实时容量 (ml)',
      nameTextStyle: { color: '#909399', fontSize: 12 },
    },
    dataZoom: [
      {
        type: 'slider',
        show: true,
        xAxisIndex: [0],
        start: 0,
        end: list.length > 15 ? 45 : 100,
        height: 20,
        bottom: 2,
      },
      {
        type: 'inside',
        xAxisIndex: [0],
      },
    ],
    series: [
      {
        name: '料桶实时容量',
        type: 'bar',
        barMaxWidth: 32,
        data: seriesData.length > 0 ? seriesData : [0],
        label: {
          show: true,
          position: 'top',
          formatter: (p: any) => (p.value > 0 ? `${p.value}` : '0'),
          fontSize: 10,
          color: '#606266',
        },
      },
    ],
  }
})

async function loadMaterials() {
  try {
    const res = await getMaterialsApi({ page_size: 200 })
    if (res.data) {
      materialOptions.value = res.data.results || []
    }
  } catch (e) {
    //
  }
}

async function fetchDetail() {
  if (!sn.value) return
  try {
    const [devRes, monRes, barRes] = await Promise.all([
      getDeviceDetailApi(sn.value),
      getMonitorDeviceDetailApi(sn.value),
      getDeviceBarrelsApi(sn.value),
    ])

    deviceInfo.value = devRes.data || {}
    snapshot.value = monRes.data || {}
    barrelsList.value = barRes.data || []
  } catch (e) {
    // 错误由拦截器提示
  }
}

function openBindDialog() {
  loadMaterials()
  bindForm.value = {
    barrel_code: '',
    material_code: materialOptions.value[0]?.code || '',
  }
  showBindDialog.value = true
}

async function handleBindBarrel() {
  if (!bindForm.value.barrel_code || !bindForm.value.material_code) {
    ElMessage.warning('请选择物料并填写料桶编号')
    return
  }

  bindLoading.value = true
  try {
    await bindDeviceBarrelApi(sn.value, bindForm.value)
    ElMessage.success('料桶映射配置成功')
    showBindDialog.value = false
    bindForm.value = { barrel_code: '', material_code: '' }
    fetchDetail()
  } catch (e) {
    // 错误处理
  } finally {
    bindLoading.value = false
  }
}

async function handleUnbindBarrel(id: number) {
  try {
    await deleteBarrelDictApi(id)
    ElMessage.success('料桶映射已解除')
    fetchDetail()
  } catch (e) {
    //
  }
}

onMounted(() => {
  fetchDetail()
  loadMaterials()
})
</script>

<style scoped lang="scss">
.kpi-row {
  margin-bottom: 12px;
}
.detail-tabs {
  background: #ffffff;
  padding: 16px 20px;
  border-radius: 8px;
}

/* 健康诊断卡片 */
.problem-diagnosis-card {
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-left: 5px solid #f56c6c;
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 16px;

  .problem-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .alert-icon {
      font-size: 18px;
    }

    .problem-title {
      font-size: 14px;
      font-weight: 600;
      color: #f56c6c;
    }
  }

  .problem-tags-container {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;

    .problem-badge {
      font-size: 13px;
      padding: 6px 12px;
      height: auto;

      .prob-cat {
        opacity: 0.85;
        margin-right: 4px;
      }
      .prob-code {
        margin-right: 4px;
      }
      .prob-desc {
        opacity: 0.95;
      }
    }
  }
}

.healthy-diagnosis-card {
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-left: 5px solid #67c23a;
  border-radius: 6px;
  padding: 10px 16px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #67c23a;
  font-weight: 500;
}

/* 图表头部与筛选 */
.chart-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;

  .sub-tip {
    font-size: 12px;
    color: #909399;
    font-weight: normal;
    margin-left: 8px;
  }
}

.chart-legend-custom {
  display: flex;
  gap: 16px;
  padding: 0 16px 8px;
  font-size: 12px;
  color: #606266;

  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;

    .dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 2px;

      &.normal {
        background-color: #409eff;
      }
      &.danger {
        background-color: #f56c6c;
      }
      &.warning {
        background-color: #e6a23c;
      }
    }
  }
}
</style>

