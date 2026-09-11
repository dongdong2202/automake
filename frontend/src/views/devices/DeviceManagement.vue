<template>
  <div class="page-container device-management-page">
    <PageHeader
      title="设备综合管理"
      subtitle="集中维护全网设备硬件档案、物理型号/类型定义、设备菜单定制以及设备海报与轮播屏保"
    >
      <template #actions>
        <el-button v-if="activeTab === 'devices'" type="primary" icon="Plus" @click="openCreateDeviceDialog">
          + 录入新设备
        </el-button>
        <el-button v-else-if="activeTab === 'models'" type="primary" icon="Plus" @click="openCreateModelDialog">
          + 录入新机型
        </el-button>
        <el-button v-else-if="activeTab === 'menus'" type="success" icon="Refresh" @click="handleSyncStoreMenu">
          从全局同步最新商品
        </el-button>
        <el-button v-else-if="activeTab === 'posters'" type="primary" icon="Plus" @click="openCreatePosterDialog">
          + 新建海报配置
        </el-button>
      </template>
    </PageHeader>

    <!-- 顶部 4 大平行选项卡 -->
    <el-tabs v-model="activeTab" type="border-card" class="device-tabs" @tab-change="handleTabChange">
      <!-- ============================================================ -->
      <!-- TAB 1: 设备档案管理 (Device List) -->
      <!-- ============================================================ -->
      <el-tab-pane name="devices">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">🖥</span>
            <span>设备档案管理</span>
            <el-badge :value="deviceTotalCount" type="primary" class="tab-badge" />
          </div>
        </template>

        <!-- 筛选表单 -->
        <el-form :inline="true" :model="deviceFilters" size="default" style="margin-bottom: 14px;">
          <el-form-item label="设备序列号/名称">
            <el-input v-model="deviceFilters.search" placeholder="输入 SN 或名称" clearable />
          </el-form-item>
          <el-form-item label="省份">
            <el-input v-model="deviceFilters.province" placeholder="按省份过滤" clearable style="width: 120px;" />
          </el-form-item>
          <el-form-item label="城市">
            <el-input v-model="deviceFilters.city" placeholder="按城市过滤" clearable style="width: 120px;" />
          </el-form-item>
          <el-form-item label="设备状态">
            <el-select v-model="deviceFilters.status" placeholder="全部状态" clearable style="width: 120px;">
              <el-option label="在线" value="online" />
              <el-option label="离线" value="offline" />
              <el-option label="故障" value="fault" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchDevices">查询</el-button>
            <el-button @click="resetDeviceFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 设备列表表格 -->
        <el-table v-loading="loadingDevices" :data="deviceList" stripe style="width: 100%">
          <el-table-column prop="device_sn" label="设备序列号 (SN)" min-width="150">
            <template #default="{ row }">
              <span style="font-family: monospace; font-weight: 600;">{{ row.device_sn }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="device_name" label="设备名称" min-width="150" />
          <el-table-column prop="key_code" label="注册码" width="120">
            <template #default="{ row }">
              <span style="font-family: monospace; color: #606266;">{{ row.key_code || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="store_name" label="所属门店" width="140">
            <template #default="{ row }">{{ row.store_name || '未分配' }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <StatusBadge :status="row.status" />
            </template>
          </el-table-column>
          <el-table-column prop="last_heartbeat_at" label="最后心跳" width="170" />
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button type="success" link size="small" @click="viewDeviceStock(row.device_sn)">
                库存
              </el-button>
              <el-button type="primary" link size="small" @click="$router.push(`/monitor/${row.device_sn}`)">
                监控
              </el-button>
              <el-button type="success" link size="small" @click="openConsumableDialog(row)">
                耗材录入
              </el-button>
              <el-button type="primary" link size="small" @click="openEditDeviceDialog(row)">
                编辑
              </el-button>
              <el-popconfirm title="确定彻底删除该设备档案吗？" @confirm="handleDeleteDevice(row.device_sn)">
                <template #reference>
                  <el-button type="danger" link size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>

        <!-- 分页 -->
        <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="devicePage"
            v-model:page-size="devicePageSize"
            :total="deviceTotalCount"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="fetchDevices"
          />
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 2: 设备型号/类型 (Device Models) -->
      <!-- ============================================================ -->
      <el-tab-pane name="models">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">⚙</span>
            <span>设备型号/类型</span>
            <el-badge :value="modelList.length" type="info" class="tab-badge" />
          </div>
        </template>

        <el-table v-loading="loadingModels" :data="modelList" stripe style="width: 100%">
          <el-table-column prop="id" label="ID" width="80" align="center" />
          <el-table-column prop="name" label="型号名称" min-width="160" />
          <el-table-column prop="code" label="型号唯一编码 (Code)" width="180">
            <template #default="{ row }">
              <el-tag size="small" type="success" effect="plain">{{ row.code }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="功能特性描述" min-width="220" show-overflow-tooltip />
          <el-table-column prop="device_count" label="绑定物理设备数" width="140" align="center">
            <template #default="{ row }">
              <el-tag :type="row.device_count > 0 ? 'primary' : 'info'" size="small">
                {{ row.device_count }} 台
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="180" />
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openEditModelDialog(row)">
                编辑
              </el-button>
              <el-popconfirm title="确定删除该型号吗？" @confirm="handleDeleteModel(row.id)">
                <template #reference>
                  <el-button type="danger" link size="small" :disabled="row.device_count > 0">
                    删除
                  </el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 3: 设备菜单定制 (Device Menu Customization) -->
      <!-- ============================================================ -->
      <el-tab-pane name="menus">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">☕</span>
            <span>设备菜单定制</span>
            <el-badge :value="storeItemList.length" type="success" class="tab-badge" />
          </div>
        </template>

        <div class="guide-tip" style="margin-bottom: 14px;">
          💡 说明：本页面展示当前门店/设备从全局菜谱继承的商品档案。支持在全局价格 ±20% 范围内微调各店售价，自由定制开启/停用可售规格（只能做减法，全局控制），修改即刻自动保存生效。
        </div>

        <!-- 工具栏 -->
        <div class="store-menu-toolbar">
          <div class="toolbar-left">
            <el-select
              v-model="selectedMenuStore"
              placeholder="请选择门店/设备归属"
              filterable
              style="width: 250px;"
              @change="fetchStoreMenuItems"
            >
              <el-option
                v-for="s in storeOptions"
                :key="s.id"
                :label="`${s.name} (ID: ${s.id})`"
                :value="s.id"
              />
            </el-select>
            <el-input
              v-model="storeMenuSearchKeyword"
              placeholder="搜索商品名称/分类..."
              clearable
              prefix-icon="Search"
              style="width: 220px;"
            />
            <el-button type="primary" icon="Refresh" @click="fetchStoreMenuItems">
              刷新
            </el-button>
            <el-button type="warning" plain icon="RefreshRight" @click="handleSyncStoreMenu">
              一键同步全局菜单
            </el-button>
          </div>
          <div class="toolbar-right">
            <el-tag type="info" effect="plain" class="count-tag">
              共 <strong>{{ filteredStoreItemList.length }}</strong> 款门店商品
            </el-tag>
          </div>
        </div>

        <el-table
          v-loading="loadingStoreItems"
          :data="filteredStoreItemList"
          stripe
          class="custom-menu-table"
          style="width: 100%"
        >
          <!-- 1. 商品基本信息 (主图 + 商品名 + 分类 + ID) -->
          <el-table-column label="商品基本信息" min-width="280">
            <template #default="{ row }">
              <div class="menu-product-cell">
                <div class="product-avatar-wrapper">
                  <el-image
                    v-if="row.image_url"
                    :src="row.image_url"
                    :preview-src-list="row.detail_page ? [row.image_url, row.detail_page] : [row.image_url]"
                    fit="cover"
                    preview-teleported
                    class="product-avatar"
                  />
                  <div v-else class="product-avatar-placeholder">
                    <span>☕</span>
                  </div>
                  <el-tooltip v-if="row.detail_page" content="包含长图详情页，点击主图可联动大图预览" placement="top">
                    <span class="detail-badge">长图</span>
                  </el-tooltip>
                </div>
                <div class="product-meta">
                  <div class="product-name-row">
                    <span class="product-name">{{ row.global_item_name }}</span>
                    <el-tag size="small" type="primary" effect="light" class="category-tag">
                      {{ row.category_name || '未分类' }}
                    </el-tag>
                  </div>
                  <div class="product-sub-row">
                    <span class="product-id">门店ID: #{{ row.id }}</span>
                    <span v-if="row.device_model_name" class="model-badge">
                      🖥 {{ row.device_model_name }}
                    </span>
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>

          <!-- 2. 门店基准售价 -->
          <el-table-column label="门店基准售价" width="130" align="right">
            <template #default="{ row }">
              <div class="store-price-cell">
                <div class="store-price-main">
                  <span class="store-currency-symbol">¥</span>
                  <span class="store-price-value">{{ (fenToYuan(row.base_price || 0)).toFixed(2) }}</span>
                </div>
                <div class="store-price-sub">
                  全局: ¥{{ (fenToYuan(row.global_base_price || 0)).toFixed(2) }}
                </div>
              </div>
            </template>
          </el-table-column>

          <!-- 3. 可售规格与分量加价 -->
          <el-table-column label="可售规格定制 (点击规格可直接调整)" min-width="320">
            <template #default="{ row }">
              <div v-if="row.skus && row.skus.length > 0" class="sku-cell-wrapper">
                <div class="sku-status-header">
                  <span class="sku-count-info">
                    已供售 <strong class="active-count">{{ getActiveSkuCount(row) }}</strong> / {{ row.skus.length }} 规格
                  </span>
                </div>
                <div class="sku-pills-list">
                  <div
                    v-for="sku in row.skus"
                    :key="sku.id"
                    class="store-sku-pill"
                    :class="{
                      'is-active': sku.is_active && sku.global_sku_is_active,
                      'is-disabled': !sku.is_active,
                      'is-global-off': !sku.global_sku_is_active
                    }"
                    @click="openDeviceSkuDialog(row)"
                  >
                    <span class="pill-name">{{ sku.template_name }}</span>
                    <span v-if="sku.price_delta > 0" class="pill-delta">
                      +¥{{ (fenToYuan(sku.price_delta)).toFixed(2) }}
                    </span>
                    <span v-if="!sku.global_sku_is_active" class="pill-badge pill-badge-off">全局关</span>
                    <span v-else-if="!sku.is_active" class="pill-badge pill-badge-pause">已停用</span>
                  </div>
                </div>
              </div>
              <div v-else class="sku-empty-wrapper">
                <span class="empty-text">暂无挂载规格</span>
              </div>
            </template>
          </el-table-column>

          <!-- 4. 上架状态 (Switch with inline-prompt) -->
          <el-table-column label="上架状态" width="110" align="center">
            <template #default="{ row }">
              <el-switch
                v-model="row.is_active"
                :loading="row.statusLoading"
                active-text="上架"
                inactive-text="下架"
                inline-prompt
                size="default"
                @change="handleToggleStoreItemStatus(row)"
              />
            </template>
          </el-table-column>

          <!-- 5. 操作 -->
          <el-table-column label="操作" width="160" fixed="right" align="center">
            <template #default="{ row }">
              <el-button
                type="primary"
                plain
                size="small"
                icon="Operation"
                @click="openDeviceSkuDialog(row)"
              >
                规格与定价定制
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 4: 设备海报屏保 (Device Posters) -->
      <!-- ============================================================ -->
      <el-tab-pane name="posters">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">🖼</span>
            <span>设备海报屏保</span>
            <el-badge :value="posterList.length" type="warning" class="tab-badge" />
          </div>
        </template>

        <el-table v-loading="loadingPosters" :data="posterList" stripe style="width: 100%">
          <el-table-column prop="version" label="版本" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="success" effect="dark">v{{ row.version }}</el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="title" label="海报配置名称" min-width="160" />

          <el-table-column label="图片缩略图 (横/竖/Banner)" width="200" align="center">
            <template #default="{ row }">
              <div style="display: flex; gap: 6px; justify-content: center; align-items: center;">
                <!-- 横屏 -->
                <el-tooltip content="横屏海报 (Horizontal)" placement="top">
                  <el-image
                    v-if="row.horizontal_image"
                    :src="row.horizontal_image"
                    :preview-src-list="[row.horizontal_image]"
                    fit="cover"
                    preview-teleported
                    style="width: 56px; height: 36px; border-radius: 4px; border: 1px solid #dcdfe6; cursor: pointer;"
                  />
                </el-tooltip>
                <!-- 竖屏 -->
                <el-tooltip content="竖屏海报 (Vertical)" placement="top">
                  <el-image
                    v-if="row.vertical_image"
                    :src="row.vertical_image"
                    :preview-src-list="[row.vertical_image]"
                    fit="cover"
                    preview-teleported
                    style="width: 28px; height: 36px; border-radius: 4px; border: 1px solid #dcdfe6; cursor: pointer;"
                  />
                </el-tooltip>
                <!-- Banner -->
                <el-tooltip content="Banner横幅" placement="top">
                  <el-image
                    v-if="row.banner_image"
                    :src="row.banner_image"
                    :preview-src-list="[row.banner_image]"
                    fit="cover"
                    preview-teleported
                    style="width: 66px; height: 36px; border-radius: 4px; border: 1px solid #dcdfe6; cursor: pointer;"
                  />
                </el-tooltip>

                <span
                  v-if="!row.horizontal_image && !row.vertical_image && !row.banner_image"
                  style="color: #909399; font-size: 12px;"
                >
                  未上传图片
                </span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="适用门店" min-width="160">
            <template #default="{ row }">
              <span v-if="!row.stores_info || row.stores_info.length === 0" style="color: #67C23A; font-weight: 500;">
                全部门店 (全局)
              </span>
              <span v-else>
                {{ row.stores_info.slice(0, 3).map((s: any) => s.name).join('、') }}
                <span v-if="row.stores_info.length > 3" style="color: #909399;">等 {{ row.stores_info.length }} 家</span>
              </span>
            </template>
          </el-table-column>

          <el-table-column label="适用设备" min-width="160">
            <template #default="{ row }">
              <span v-if="!row.devices_info || row.devices_info.length === 0" style="color: #909399;">
                全部设备 (通用)
              </span>
              <span v-else>
                {{ row.devices_info.slice(0, 3).map((d: any) => d.device_name || d.device_sn).join('、') }}
                <span v-if="row.devices_info.length > 3" style="color: #909399;">等 {{ row.devices_info.length }} 台</span>
              </span>
            </template>
          </el-table-column>

          <el-table-column prop="remarks" label="备注" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.remarks || '-' }}</template>
          </el-table-column>

          <el-table-column prop="sort_order" label="排序权重" width="100" align="center" sortable />

          <el-table-column label="是否启用" width="100" align="center">
            <template #default="{ row }">
              <el-switch v-model="row.is_active" @change="handleTogglePosterStatus(row)" />
            </template>
          </el-table-column>

          <el-table-column prop="created_at" label="创建时间" width="170" />

          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openEditPosterDialog(row)">
                编辑配置
              </el-button>
              <el-popconfirm title="确定删除该海报配置吗？" @confirm="handleDeletePoster(row.id)">
                <template #reference>
                  <el-button type="danger" link size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- ============================================================ -->
      <!-- TAB 5: 设备库存流水 (Device Stock & Refill Records) -->
      <!-- ============================================================ -->
      <el-tab-pane name="stocks">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">📋</span>
            <span>设备库存流水</span>
            <el-badge :value="deviceRecordTotalCount" type="primary" class="tab-badge" />
          </div>
        </template>

        <!-- 筛选表单 -->
        <el-form :inline="true" :model="deviceRecordFilters" size="default" style="margin-bottom: 14px;">
          <el-form-item label="选择门店">
            <el-select
              v-model="deviceRecordFilters.store_id"
              placeholder="全部门店"
              clearable
              filterable
              style="width: 200px;"
              @change="onDeviceRecordStoreChange"
            >
              <el-option
                v-for="s in storeOptions"
                :key="s.id"
                :label="`${s.name} (ID: ${s.id})`"
                :value="s.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="选择设备">
            <el-select
              v-model="deviceRecordFilters.device_sn"
              placeholder="全部设备"
              clearable
              filterable
              style="width: 220px;"
              @change="fetchDeviceRecords"
            >
              <el-option
                v-for="d in filteredDeviceOptions"
                :key="d.device_sn"
                :label="`${d.device_name || d.device_sn} (${d.device_sn})`"
                :value="d.device_sn"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="关键字搜索">
            <el-input v-model="deviceRecordFilters.search" placeholder="搜索物料/设备/备注" clearable />
          </el-form-item>

          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchDeviceRecords">查询流水</el-button>
            <el-button @click="resetDeviceRecordFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 设备流水表格 -->
        <el-table v-loading="loadingDeviceRecords" :data="deviceRecordList" stripe style="width: 100%">
          <el-table-column prop="id" label="流水ID" width="90" align="center" />
          <el-table-column prop="device_name" label="目标设备" width="180">
            <template #default="{ row }">
              <div style="display: flex; flex-direction: column;">
                <span style="font-weight: 600;">{{ row.device_name || row.device_sn }}</span>
                <span style="font-size: 11px; color: #909399; font-family: monospace;">{{ row.device_sn }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="store_name" label="所属门店" min-width="150">
            <template #default="{ row }">
              <span style="font-weight: 500;">{{ row.store_name || `门店 #${row.store}` }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="record_type" label="流转类型" width="150">
            <template #default="{ row }">
              <el-tag type="primary" effect="dark" size="small">
                📤 门店加料到设备
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="material_name" label="加料物料" min-width="160">
            <template #default="{ row }">
              <div style="display: flex; flex-direction: column;">
                <span style="font-weight: 500;">{{ row.material_name }}</span>
                <span style="font-size: 11px; color: #909399; font-family: monospace;">{{ row.material_code }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="加料数量" width="130">
            <template #default="{ row }">
              <span style="font-weight: bold; color: #409EFF;">
                +{{ row.quantity }} {{ row.material_unit }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="operator_username" label="经办操作员" width="120">
            <template #default="{ row }">{{ row.operator_username || '系统自动' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="加料发生时间" width="170" />
          <el-table-column prop="remarks" label="备注说明" min-width="180" show-overflow-tooltip />
        </el-table>

        <!-- 分页 -->
        <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="deviceRecordPage"
            v-model:page-size="deviceRecordPageSize"
            :total="deviceRecordTotalCount"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="fetchDeviceRecords"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ============================================================ -->
    <!-- 对话框 0: 设备耗材补货与库存调整 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showConsumableDialog"
      title="设备耗材库存补货 / 盘点录入"
      width="600px"
      destroy-on-close
    >
      <div style="margin-bottom: 14px; font-size: 13px; color: #606266;">
        当前设备: <strong>{{ currentConsumableDevice?.device_name || currentConsumableDevice?.device_sn }}</strong> 
        <el-tag size="small" type="info" style="margin-left: 8px;">{{ currentConsumableDevice?.device_sn }}</el-tag>
      </div>
      <el-alert
        title="耗材（纸杯、塑料杯、杯盖、封口膜）由人工维护，提交后将实时写入数据库并 1:1 同步刷新 Redis 可用库存。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px;"
      />
      <el-table :data="consumableFormList" border size="small">
        <el-table-column prop="name" label="耗材类型" min-width="140">
          <template #default="{ row }">
            <span style="font-weight: 500;">{{ row.name }}</span>
            <div style="font-size: 12px; color: #909399;">{{ row.code }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="80" align="center" />
        <el-table-column label="最新库存 (实盘录入)" width="200" align="center">
          <template #default="{ row }">
            <el-input-number
              v-model="row.quantity"
              :min="0"
              :max="5000"
              :step="10"
              size="small"
              controls-position="right"
              style="width: 150px;"
            />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="showConsumableDialog = false">取消</el-button>
        <el-button type="primary" :loading="submittingConsumables" @click="submitConsumableUpdate">
          确认录入并同步
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 1: 录入/编辑设备档案 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showDeviceDialog"
      :title="isEditDevice ? '编辑设备档案' : '录入新设备'"
      width="640px"
      top="7vh"
      destroy-on-close
      class="device-form-dialog"
    >
      <el-form :model="deviceFormData" label-position="top" class="device-modal-form">
        <!-- 分区 1: 基础档案 -->
        <div class="form-section-card">
          <div class="section-card-header">
            <span class="section-card-tag"></span>
            <span class="section-card-title">基本档案</span>
            <span class="section-card-tip">设备的硬件唯一标识与归属机型</span>
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="设备序列号 (SN)" required>
                <el-input
                  v-model="deviceFormData.device_sn"
                  :disabled="isEditDevice"
                  placeholder="出厂唯一编码，如 SN001"
                  clearable
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="设备名称" required>
                <el-input
                  v-model="deviceFormData.device_name"
                  placeholder="如 朝阳大悦城1号机"
                  clearable
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="分配所属门店" class="mb-0">
                <el-select
                  v-model="deviceFormData.store"
                  placeholder="请选择门店"
                  filterable
                  clearable
                  style="width: 100%;"
                >
                  <el-option
                    v-for="store in storeOptions"
                    :key="store.id"
                    :label="`${store.name} (ID: ${store.id})`"
                    :value="store.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="硬件设备型号" class="mb-0">
                <el-select
                  v-model="deviceFormData.device_model"
                  placeholder="请选择硬件机型"
                  clearable
                  style="width: 100%;"
                >
                  <el-option
                    v-for="model in modelList"
                    :key="model.id"
                    :label="`${model.name} (${model.code})`"
                    :value="model.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 分区 2: 点位与布设地址 -->
        <div class="form-section-card">
          <div class="section-card-header">
            <span class="section-card-tag"></span>
            <span class="section-card-title">布设位置</span>
            <span class="section-card-tip">点位所在的行政省市、经纬度及具体安装位置</span>
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="所在省份">
                <el-input v-model="deviceFormData.province" placeholder="如 北京市、广东省" clearable />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="所在城市">
                <el-input v-model="deviceFormData.city" placeholder="如 北京市、深圳市" clearable />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="经度 (lng)">
                <el-input-number
                  v-model="deviceFormData.lng"
                  :precision="6"
                  :step="0.0001"
                  controls-position="right"
                  placeholder="如 116.4074"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="纬度 (lat)">
                <el-input-number
                  v-model="deviceFormData.lat"
                  :precision="6"
                  :step="0.0001"
                  controls-position="right"
                  placeholder="如 39.9042"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="详细布设地址" class="mb-0">
            <el-input
              v-model="deviceFormData.address"
              placeholder="如 朝阳区朝阳北路101号大悦城B1层中庭咖啡角"
              clearable
            />
          </el-form-item>
        </div>

        <!-- 分区 3: 运行与版本 -->
        <div class="form-section-card">
          <div class="section-card-header">
            <span class="section-card-tag"></span>
            <span class="section-card-title">运行与版本</span>
            <span class="section-card-tip">运行状态、鉴权注册码及软固件版本</span>
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="设备状态">
                <el-select v-model="deviceFormData.status" style="width: 100%;">
                  <el-option label="在线 (online)" value="online" />
                  <el-option label="离线 (offline)" value="offline" />
                  <el-option label="故障 (fault)" value="fault" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="门店注册码 (key_code)">
                <el-input v-model="deviceFormData.key_code" placeholder="用于设备上线鉴权注册" clearable />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="固件版本" class="mb-0">
                <el-input v-model="deviceFormData.firmware_version" placeholder="如 1.0.0 或 2.1.4" clearable />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="静态资源版本" class="mb-0">
                <el-input
                  v-model="deviceFormData.resource_version"
                  placeholder="如 0 或 101"
                  clearable
                />
              </el-form-item>
            </el-col>
          </el-row>
        </div>
      </el-form>
      <template #footer>
        <div class="dialog-footer-actions">
          <el-button @click="showDeviceDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitDeviceLoading" @click="handleSubmitDevice">
            确认保存
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 2: 新增/编辑型号 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showModelDialog"
      :title="isEditModel ? '编辑设备型号' : '录入新设备型号'"
      width="520px"
    >
      <el-form :model="modelFormData" label-width="100px">
        <el-form-item label="型号名称" required>
          <el-input v-model="modelFormData.name" placeholder="例如 智能现磨咖啡机 A1型" />
        </el-form-item>
        <el-form-item label="型号编码" required>
          <el-input v-model="modelFormData.code" placeholder="全局唯一编码，如 MODEL-A1" />
        </el-form-item>
        <el-form-item label="功能描述">
          <el-input
            v-model="modelFormData.description"
            type="textarea"
            :rows="3"
            placeholder="说明该型号的硬件特性（如：双出料口、自带冷柜与制冰机模块等）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showModelDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitModelLoading" @click="handleSubmitModel">
          确认保存
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 3: 新增/编辑海报配置 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showPosterDialog"
      :title="isEditPoster ? `编辑海报配置 (ID: ${currentPosterId})` : '新建海报配置'"
      width="780px"
      top="4vh"
    >
      <el-form :model="posterFormData" label-position="top">
        <!-- 分区 1: 基本配置 -->
        <el-card shadow="never" class="form-section-card">
          <template #header>
            <span class="section-title">📌 基本配置</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="16">
              <el-form-item label="海报配置名称" required>
                <el-input v-model="posterFormData.title" placeholder="例如：秋季新品推广、默认轮播海报等" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="版本号 (整数唯一)">
                <el-input-number
                  v-model="posterFormData.version"
                  :min="1"
                  :step="1"
                  placeholder="留空自动在最大版本+1"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="16">
              <el-form-item label="备注说明">
                <el-input v-model="posterFormData.remarks" placeholder="例如：秋季开业海报、中秋限定海报等" />
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="排序权重">
                <el-input-number v-model="posterFormData.sort_order" :min="0" :max="999" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="是否启用">
                <el-switch v-model="posterFormData.is_active" active-text="启用" inactive-text="下架" />
              </el-form-item>
            </el-col>
          </el-row>
        </el-card>

        <!-- 分区 2: 海报图片上传 (3个独立上传项与预览) -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <span class="section-title">🖼 海报图片上传 (3个独立上传项)</span>
          </template>

          <el-row :gutter="16">
            <!-- 横屏海报 -->
            <el-col :span="8">
              <div class="poster-upload-box">
                <div class="upload-label">横屏海报 (horizontal)</div>
                <div class="upload-desc">用于横屏点单机/待机屏保</div>
                <div class="preview-container horizontal-box">
                  <el-image
                    v-if="posterFormData.horizontal_image"
                    :src="posterFormData.horizontal_image"
                    fit="contain"
                    class="preview-img"
                  />
                  <div v-else class="empty-tip">暂无图片</div>
                </div>
                <div class="upload-actions">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(file: any) => handleUploadPosterFile(file, 'horizontal_image')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传横屏</el-button>
                  </el-upload>
                  <el-button
                    v-if="posterFormData.horizontal_image"
                    size="small"
                    type="danger"
                    link
                    @click="posterFormData.horizontal_image = ''"
                  >
                    清空
                  </el-button>
                </div>
                <el-input
                  v-model="posterFormData.horizontal_image"
                  size="small"
                  placeholder="或直接粘贴图片 URL"
                  style="margin-top: 6px;"
                />
              </div>
            </el-col>

            <!-- 竖屏海报 -->
            <el-col :span="8">
              <div class="poster-upload-box">
                <div class="upload-label">竖屏海报 (vertical)</div>
                <div class="upload-desc">用于竖屏机器/立式屏幕</div>
                <div class="preview-container vertical-box">
                  <el-image
                    v-if="posterFormData.vertical_image"
                    :src="posterFormData.vertical_image"
                    fit="contain"
                    class="preview-img"
                  />
                  <div v-else class="empty-tip">暂无图片</div>
                </div>
                <div class="upload-actions">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(file: any) => handleUploadPosterFile(file, 'vertical_image')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传竖屏</el-button>
                  </el-upload>
                  <el-button
                    v-if="posterFormData.vertical_image"
                    size="small"
                    type="danger"
                    link
                    @click="posterFormData.vertical_image = ''"
                  >
                    清空
                  </el-button>
                </div>
                <el-input
                  v-model="posterFormData.vertical_image"
                  size="small"
                  placeholder="或直接粘贴图片 URL"
                  style="margin-top: 6px;"
                />
              </div>
            </el-col>

            <!-- Banner海报 -->
            <el-col :span="8">
              <div class="poster-upload-box">
                <div class="upload-label">横幅海报 (banner)</div>
                <div class="upload-desc">用于小程序顶部横幅/通栏广告</div>
                <div class="preview-container banner-box">
                  <el-image
                    v-if="posterFormData.banner_image"
                    :src="posterFormData.banner_image"
                    fit="contain"
                    class="preview-img"
                  />
                  <div v-else class="empty-tip">暂无图片</div>
                </div>
                <div class="upload-actions">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(file: any) => handleUploadPosterFile(file, 'banner_image')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传Banner</el-button>
                  </el-upload>
                  <el-button
                    v-if="posterFormData.banner_image"
                    size="small"
                    type="danger"
                    link
                    @click="posterFormData.banner_image = ''"
                  >
                    清空
                  </el-button>
                </div>
                <el-input
                  v-model="posterFormData.banner_image"
                  size="small"
                  placeholder="或直接粘贴图片 URL"
                  style="margin-top: 6px;"
                />
              </div>
            </el-col>
          </el-row>
        </el-card>

        <!-- 分区 3: 适用范围 (门店与设备多选) -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <span class="section-title">🏢 适用范围 (门店与设备多选)</span>
            <span style="color: #909399; font-size: 12px; margin-left: 10px;">
              留空则表示对全系统所有门店与设备全局生效
            </span>
          </template>

          <el-form-item label="指定适用门店 (多选)">
            <el-select
              v-model="posterFormData.stores"
              multiple
              filterable
              placeholder="留空表示全部门店生效"
              style="width: 100%;"
            >
              <el-option
                v-for="s in storeOptions"
                :key="s.id"
                :label="`${s.name} (ID: ${s.id})`"
                :value="s.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="指定适用设备 (多选)">
            <el-select
              v-model="posterFormData.devices"
              multiple
              filterable
              placeholder="留空表示全部设备通用"
              style="width: 100%;"
            >
              <el-option
                v-for="d in deviceOptions"
                :key="d.id"
                :label="`${d.device_name || '咖啡机'} (${d.device_sn})`"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
        </el-card>

        <!-- 分区 4: 审计信息 (编辑时展示) -->
        <div v-if="isEditPoster" style="margin-top: 10px; color: #909399; font-size: 12px; text-align: right;">
          创建时间：{{ posterFormData.created_at || '-' }} | 最后更新：{{ posterFormData.updated_at || '-' }}
        </div>
      </el-form>

      <template #footer>
        <el-button @click="showPosterDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitPosterLoading" @click="handleSubmitPoster">
          确认保存配置
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 4: 设备可售规格定制 (只能做减法，受全局控制) -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showDeviceSkuDialog"
      :title="`【${currentStoreItem?.global_item_name || '商品'}】设备规格与定价定制`"
      width="860px"
    >
      <!-- 顶部基准价格设置卡片 -->
      <div style="background: #f8f9fb; border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 18px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
          <div>
            <div style="font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 4px;">
              {{ currentStoreItem?.global_item_name }}
              <el-tag size="small" type="info" style="margin-left: 8px;">{{ currentStoreItem?.category_name }}</el-tag>
            </div>
            <div style="font-size: 12px; color: #909399;">
              全局基准售价：<span style="color: #606266; font-weight: 500;">¥{{ (fenToYuan(currentStoreItem?.global_base_price || 0)).toFixed(2) }}</span>
              <span style="margin-left: 12px;">上下20%浮动范围：<span style="color: #E6A23C; font-weight: 500;">¥{{ minBasePriceYuan.toFixed(2) }} ~ ¥{{ maxBasePriceYuan.toFixed(2) }}</span></span>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 13px; font-weight: 600; color: #606266;">本店基准售价 (元)：</span>
            <el-input-number
              v-model="editStoreItemBasePriceYuan"
              :min="minBasePriceYuan"
              :max="maxBasePriceYuan"
              :step="0.5"
              :precision="2"
              size="default"
              style="width: 140px;"
              @change="handleSaveStoreItemBasePrice"
            />
          </div>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <div style="font-size: 13px; font-weight: 600; color: #303133;">
          📋 规格分量加价定制 (继承全局分量价格，允许上下 20% 范围修改)
        </div>
        <el-button size="small" icon="Refresh" @click="fetchCurrentStoreItemSkus">
          刷新规格
        </el-button>
      </div>

      <el-table v-loading="loadingDeviceSkus" :data="currentStoreItemSkus" size="small" stripe border style="width: 100%;">
        <el-table-column label="规格名称" min-width="150">
          <template #default="{ row }">
            <span style="font-weight: 600; color: #303133;">{{ row.template_name }}</span>
            <el-tag size="small" type="info" style="margin-left: 6px;">{{ row.template_category || '-' }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="分量加价 (元)" width="180" align="center">
          <template #default="{ row }">
            <el-input-number
              v-model="row.editPriceDeltaYuan"
              :min="row.minDeltaYuan"
              :max="row.maxDeltaYuan"
              :step="0.5"
              :precision="2"
              :loading="row.priceLoading"
              size="small"
              style="width: 100%;"
              @change="handleDeviceSkuPriceDeltaChange(row)"
            />
          </template>
        </el-table-column>

        <el-table-column label="允许加价范围 (±20%)" width="190" align="center">
          <template #default="{ row }">
            <div style="font-size: 12px; color: #606266; font-weight: 500;">
              {{ row.minDeltaYuan >= 0 ? '+' : '' }}{{ (row.minDeltaYuan || 0).toFixed(2) }} ~ {{ row.maxDeltaYuan >= 0 ? '+' : '' }}{{ (row.maxDeltaYuan || 0).toFixed(2) }} 元
            </div>
            <div style="font-size: 10px; color: #909399;">
              (全局默认: +{{ (row.globalDeltaYuan || 0).toFixed(2) }} 元)
            </div>
          </template>
        </el-table-column>

        <el-table-column label="本设备状态" width="120" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="!row.global_sku_is_active"
              content="全局规格已停用，设备端无法单独开启（只能做减法，受全局控制）"
              placement="top"
            >
              <el-switch
                v-model="row.is_active"
                disabled
                active-text="启用"
                inactive-text="停用"
                size="small"
              />
            </el-tooltip>
            <el-switch
              v-else
              v-model="row.is_active"
              :loading="row.statusLoading"
              active-text="启用"
              inactive-text="停用"
              size="small"
              @change="(val: boolean) => handleToggleDeviceSkuStatus(row, val)"
            />
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button type="primary" @click="showDeviceSkuDialog = false">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Search, Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  getDevicesApi,
  createDeviceApi,
  updateDeviceApi,
  deleteDeviceApi,
  getPostersApi,
  createPosterApi,
  updatePosterApi,
  deletePosterApi,
  getDeviceInventoryRecordsApi,
  getDeviceStocksOverviewApi,
  updateDeviceConsumablesApi,
} from '@/api/devices'
import {
  getDeviceModelsApi,
  createDeviceModelApi,
  updateDeviceModelApi,
  deleteDeviceModelApi,
} from '@/api/global_config'
import {
  getStoreMenuItemsApi,
  updateStoreMenuItemApi,
  getStoreItemSkusApi,
  updateStoreMenuSkuApi,
  syncStoreMenuApi,
} from '@/api/menus'
import { getStoresApi } from '@/api/stores'
import { uploadFileApi } from '@/api/common'
import { useAuthStore } from '@/stores/auth'
import { fenToYuan, yuanToFen, formatCurrency } from '@/utils/money'
import type { DeviceItem, DeviceModelItem, StoreItem, PosterItem, StoreMenuItem, StoreMenuSku } from '@/types'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 选项卡状态 (devices | models | menus | posters)
const activeTab = ref<string>('devices')

// -------------------------------------------------------------
// 1. 设备档案相关数据
// -------------------------------------------------------------
const loadingDevices = ref(false)
const deviceList = ref<DeviceItem[]>([])
const deviceTotalCount = ref(0)
const devicePage = ref(1)
const devicePageSize = ref(10)

const deviceFilters = reactive({
  search: '',
  status: '',
  province: '',
  city: '',
  store_id: undefined as number | undefined,
})

const showDeviceDialog = ref(false)
const isEditDevice = ref(false)
const submitDeviceLoading = ref(false)
const currentDeviceSn = ref('')

// 耗材补货与盘点录入
const showConsumableDialog = ref(false)
const submittingConsumables = ref(false)
const currentConsumableDevice = ref<any>(null)
const consumableFormList = ref([
  { code: 'paperL', name: '大号纸杯', unit: '个', quantity: 100 },
  { code: 'paperM', name: '中号纸杯', unit: '个', quantity: 100 },
  { code: 'plasticL', name: '大号塑料杯', unit: '个', quantity: 100 },
  { code: 'plasticM', name: '中号塑料杯', unit: '个', quantity: 100 },
  { code: 'lid', name: '杯盖', unit: '个', quantity: 150 },
  { code: 'membrane', name: '封口膜', unit: '张', quantity: 500 },
])

const openConsumableDialog = async (device: any) => {
  currentConsumableDevice.value = device
  showConsumableDialog.value = true
  try {
    const res = await getDeviceStocksOverviewApi({ device_sn: device.device_sn })
    if (res.data && res.data.length > 0 && res.data[0].consumables) {
      const dbCons = res.data[0].consumables
      consumableFormList.value.forEach(item => {
        const found = dbCons.find((c: any) => c.code === item.code)
        if (found) {
          item.quantity = found.quantity
        }
      })
    }
  } catch (err) {
    console.error('加载当前耗材库存失败:', err)
  }
}

const submitConsumableUpdate = async () => {
  if (!currentConsumableDevice.value) return
  submittingConsumables.value = true
  try {
    const items = consumableFormList.value.map(item => ({
      code: item.code,
      quantity: item.quantity,
    }))
    await updateDeviceConsumablesApi(currentConsumableDevice.value.device_sn, items)
    ElMessage.success('耗材库存已成功录入并实时同步至 Redis！')
    showConsumableDialog.value = false
  } catch (err: any) {
    ElMessage.error(err?.message || '耗材库存更新失败')
  } finally {
    submittingConsumables.value = false
  }
}

const deviceFormData = reactive({
  device_sn: '',
  device_name: '',
  key_code: '',
  status: 'offline',
  store: undefined as number | undefined | null,
  device_model: undefined as number | undefined | null,
  province: '',
  city: '',
  address: '',
  firmware_version: '',
  resource_version: 0 as string | number,
  lat: null as number | null,
  lng: null as number | null,
  mqtt_topic_prefix: '',
  gps_coordinate: '',
  extra_config: {} as Record<string, any>,
})

// -------------------------------------------------------------
// 2. 设备型号相关数据
// -------------------------------------------------------------
const loadingModels = ref(false)
const modelList = ref<DeviceModelItem[]>([])
const showModelDialog = ref(false)
const isEditModel = ref(false)
const submitModelLoading = ref(false)
const currentModelId = ref<number | null>(null)

const modelFormData = reactive({
  name: '',
  code: '',
  description: '',
})

// -------------------------------------------------------------
// 3. 设备菜单定制相关数据
// -------------------------------------------------------------
const loadingStoreItems = ref(false)
const selectedMenuStore = ref<number | ''>('')
const storeItemList = ref<StoreMenuItem[]>([])
const storeMenuSearchKeyword = ref('')
const filteredStoreItemList = computed(() => {
  if (!storeMenuSearchKeyword.value.trim()) return storeItemList.value
  const kw = storeMenuSearchKeyword.value.trim().toLowerCase()
  return storeItemList.value.filter((item: StoreMenuItem) => {
    const nameMatch = (item.global_item_name || '').toLowerCase().includes(kw)
    const catMatch = (item.category_name || '').toLowerCase().includes(kw)
    const idMatch = String(item.id).includes(kw)
    return nameMatch || catMatch || idMatch
  })
})
const showDeviceSkuDialog = ref(false)
const currentStoreItem = ref<StoreMenuItem | null>(null)
const currentStoreItemSkus = ref<any[]>([])
const loadingDeviceSkus = ref(false)
const editStoreItemBasePriceYuan = ref<number>(0)

const minBasePriceYuan = computed(() => {
  if (!currentStoreItem.value?.global_base_price) return 0.01
  return Number((fenToYuan(currentStoreItem.value.global_base_price) * 0.8).toFixed(2))
})

const maxBasePriceYuan = computed(() => {
  if (!currentStoreItem.value?.global_base_price) return 999
  return Number((fenToYuan(currentStoreItem.value.global_base_price) * 1.2).toFixed(2))
})

// -------------------------------------------------------------
// 4. 设备海报屏保相关数据
// -------------------------------------------------------------
const loadingPosters = ref(false)
const posterList = ref<PosterItem[]>([])
const showPosterDialog = ref(false)
const isEditPoster = ref(false)
const submitPosterLoading = ref(false)
const currentPosterId = ref<number | null>(null)

const posterFormData = reactive<any>({
  title: '',
  version: undefined,
  remarks: '',
  sort_order: 0,
  is_active: true,
  horizontal_image: '',
  vertical_image: '',
  banner_image: '',
  stores: [],
  devices: [],
  created_at: '',
  updated_at: '',
})

// -------------------------------------------------------------
// 5. 设备库存加料流水
// -------------------------------------------------------------
const loadingDeviceRecords = ref(false)
const deviceRecordList = ref<any[]>([])
const deviceRecordTotalCount = ref(0)
const deviceRecordPage = ref(1)
const deviceRecordPageSize = ref(20)

const deviceRecordFilters = reactive({
  store_id: undefined as number | undefined,
  device_sn: '',
  search: '',
})

// 门店及设备通用下拉候选
const storeOptions = ref<StoreItem[]>([])
const deviceOptions = ref<DeviceItem[]>([])

const filteredDeviceOptions = computed(() => {
  if (!deviceRecordFilters.store_id) {
    return deviceOptions.value
  }
  return deviceOptions.value.filter((d: any) => d.store === deviceRecordFilters.store_id || d.store_id === deviceRecordFilters.store_id)
})

function onDeviceRecordStoreChange() {
  deviceRecordFilters.device_sn = ''
  deviceRecordPage.value = 1
  fetchDeviceRecords()
}

async function fetchDeviceRecords() {
  loadingDeviceRecords.value = true
  try {
    const res = await getDeviceInventoryRecordsApi({
      page: deviceRecordPage.value,
      page_size: deviceRecordPageSize.value,
      store_id: deviceRecordFilters.store_id,
      device_sn: deviceRecordFilters.device_sn,
      search: deviceRecordFilters.search,
    })
    deviceRecordList.value = res.data.results || []
    deviceRecordTotalCount.value = res.data.count || 0
  } catch (err: any) {
    ElMessage.error(err.message || '获取设备加料流水失败')
  } finally {
    loadingDeviceRecords.value = false
  }
}

function resetDeviceRecordFilters() {
  deviceRecordFilters.store_id = undefined
  deviceRecordFilters.device_sn = ''
  deviceRecordFilters.search = ''
  deviceRecordPage.value = 1
  fetchDeviceRecords()
}

function viewDeviceStock(sn: string) {
  deviceRecordFilters.device_sn = sn
  activeTab.value = 'stocks'
  router.replace({
    path: '/devices',
    query: { tab: 'stocks' },
  })
  fetchDeviceRecords()
}

// -------------------------------------------------------------
// 选项卡切换与 URL 联动
// -------------------------------------------------------------
function handleTabChange(tabName: any) {
  router.replace({
    path: '/devices',
    query: { tab: tabName },
  })
  if (tabName === 'stocks') {
    fetchDeviceRecords()
  } else if (tabName === 'menus') {
    fetchStoreMenuItems()
  }
}

// -------------------------------------------------------------
// 数据获取
// -------------------------------------------------------------
async function fetchStores() {
  try {
    const res = await getStoresApi({ page_size: 200 })
    if (res.data) {
      storeOptions.value = res.data.results || []
      if (!selectedMenuStore.value && storeOptions.value.length > 0) {
        selectedMenuStore.value = authStore.selectedStoreId || storeOptions.value[0].id
      }
    }
  } catch (e) {
    //
  }
}

async function fetchDevices() {
  loadingDevices.value = true
  try {
    const params = {
      page: devicePage.value,
      page_size: devicePageSize.value,
      search: deviceFilters.search,
      status: deviceFilters.status,
      province: deviceFilters.province,
      city: deviceFilters.city,
      store_id: deviceFilters.store_id,
    }
    const res = await getDevicesApi(params)
    if (res.data) {
      deviceList.value = res.data.results || []
      deviceTotalCount.value = res.data.count || 0
      deviceOptions.value = res.data.results || []
    }
  } finally {
    loadingDevices.value = false
  }
}

function resetDeviceFilters() {
  deviceFilters.search = ''
  deviceFilters.status = ''
  deviceFilters.province = ''
  deviceFilters.city = ''
  deviceFilters.store_id = undefined
  devicePage.value = 1
  fetchDevices()
}

async function fetchModels() {
  loadingModels.value = true
  try {
    const res = await getDeviceModelsApi()
    if (res.data) {
      modelList.value = res.data
    }
  } finally {
    loadingModels.value = false
  }
}

async function fetchStoreMenuItems() {
  loadingStoreItems.value = true
  try {
    const storeId = selectedMenuStore.value || authStore.selectedStoreId || (storeOptions.value[0]?.id)
    if (!selectedMenuStore.value && storeId) {
      selectedMenuStore.value = storeId
    }
    const params: any = { page_size: 200 }
    if (storeId) {
      params.store_id = storeId
    }
    const res = await getStoreMenuItemsApi(params)
    if (res.data) {
      storeItemList.value = (res.data.results || []).map((item: any) => ({
        ...item,
        editPriceYuan: fenToYuan(item.base_price),
        statusLoading: false,
      }))
    }
  } finally {
    loadingStoreItems.value = false
  }
}

async function fetchPosters() {
  loadingPosters.value = true
  try {
    const res = await getPostersApi()
    if (res.data) {
      posterList.value = res.data
    }
  } finally {
    loadingPosters.value = false
  }
}

function reloadAll() {
  fetchStores()
  fetchDevices()
  fetchModels()
  fetchStoreMenuItems()
  fetchPosters()
  fetchDeviceRecords()
}

// -------------------------------------------------------------
// 设备档案操作
// -------------------------------------------------------------
function openCreateDeviceDialog() {
  isEditDevice.value = false
  currentDeviceSn.value = ''
  Object.assign(deviceFormData, {
    device_sn: '',
    device_name: '',
    key_code: '',
    status: 'offline',
    store: storeOptions.value[0]?.id || undefined,
    device_model: modelList.value[0]?.id || undefined,
    province: '',
    city: '',
    address: '',
    firmware_version: '',
    resource_version: 0,
    lat: null,
    lng: null,
    mqtt_topic_prefix: '',
    gps_coordinate: '',
    extra_config: {},
  })
  showDeviceDialog.value = true
}

function openEditDeviceDialog(row: DeviceItem) {
  isEditDevice.value = true
  currentDeviceSn.value = row.device_sn

  let latVal: number | null = row.lat !== undefined && row.lat !== null ? Number(row.lat) : null
  let lngVal: number | null = row.lng !== undefined && row.lng !== null ? Number(row.lng) : null
  if ((latVal === null || lngVal === null) && row.gps_coordinate && row.gps_coordinate.includes(',')) {
    const parts = row.gps_coordinate.split(',').map(p => parseFloat(p.trim()))
    if (!isNaN(parts[0]) && !isNaN(parts[1])) {
      if (parts[0] > 60) {
        lngVal = parts[0]
        latVal = parts[1]
      } else {
        latVal = parts[0]
        lngVal = parts[1]
      }
    }
  }

  Object.assign(deviceFormData, {
    device_sn: row.device_sn,
    device_name: row.device_name,
    key_code: row.key_code || '',
    status: row.status,
    store: row.store,
    device_model: row.device_model,
    province: row.province || '',
    city: row.city || '',
    address: row.address || '',
    firmware_version: row.firmware_version || '',
    resource_version: row.resource_version || 0,
    lat: latVal,
    lng: lngVal,
    mqtt_topic_prefix: row.mqtt_topic_prefix || '',
    gps_coordinate: row.gps_coordinate || '',
    extra_config: row.extra_config || {},
  })
  showDeviceDialog.value = true
}

async function handleSubmitDevice() {
  if (!deviceFormData.device_sn?.trim() || !deviceFormData.device_name?.trim()) {
    ElMessage.warning('设备序列号和设备名称为必填项')
    return
  }

  const latNum = deviceFormData.lat !== null && deviceFormData.lat !== undefined && !isNaN(Number(deviceFormData.lat))
    ? Number(deviceFormData.lat)
    : null
  const lngNum = deviceFormData.lng !== null && deviceFormData.lng !== undefined && !isNaN(Number(deviceFormData.lng))
    ? Number(deviceFormData.lng)
    : null
  const gpsCoord = (lngNum !== null && latNum !== null)
    ? `${lngNum},${latNum}`
    : (deviceFormData.gps_coordinate || '')

  const payload: any = {
    device_sn: deviceFormData.device_sn.trim(),
    device_name: deviceFormData.device_name.trim(),
    key_code: deviceFormData.key_code ? deviceFormData.key_code.trim() : '',
    status: deviceFormData.status,
    store: deviceFormData.store || null,
    device_model: deviceFormData.device_model || null,
    province: deviceFormData.province ? deviceFormData.province.trim() : '',
    city: deviceFormData.city ? deviceFormData.city.trim() : '',
    address: deviceFormData.address ? deviceFormData.address.trim() : '',
    firmware_version: deviceFormData.firmware_version ? deviceFormData.firmware_version.trim() : '',
    resource_version: Number(deviceFormData.resource_version) || 0,
    lat: latNum,
    lng: lngNum,
    mqtt_topic_prefix: deviceFormData.mqtt_topic_prefix || '',
    gps_coordinate: gpsCoord,
    extra_config: deviceFormData.extra_config || {},
  }

  submitDeviceLoading.value = true
  try {
    if (isEditDevice.value) {
      await updateDeviceApi(currentDeviceSn.value, payload)
      ElMessage.success('设备配置已成功更新')
    } else {
      await createDeviceApi(payload)
      ElMessage.success('设备已成功录入')
    }
    showDeviceDialog.value = false
    fetchDevices()
  } finally {
    submitDeviceLoading.value = false
  }
}

async function handleDeleteDevice(sn: string) {
  try {
    await deleteDeviceApi(sn)
    ElMessage.success(`设备 [${sn}] 已成功删除`)
    fetchDevices()
  } catch (e) {
    // 错误拦截器统一处理
  }
}

// -------------------------------------------------------------
// 设备型号操作
// -------------------------------------------------------------
function openCreateModelDialog() {
  isEditModel.value = false
  currentModelId.value = null
  Object.assign(modelFormData, {
    name: '',
    code: '',
    description: '',
  })
  showModelDialog.value = true
}

function openEditModelDialog(row: DeviceModelItem) {
  isEditModel.value = true
  currentModelId.value = row.id
  Object.assign(modelFormData, {
    name: row.name,
    code: row.code,
    description: row.description || '',
  })
  showModelDialog.value = true
}

async function handleSubmitModel() {
  if (!modelFormData.name || !modelFormData.code) {
    ElMessage.warning('型号名称和编码为必填项')
    return
  }

  submitModelLoading.value = true
  try {
    if (isEditModel.value && currentModelId.value) {
      await updateDeviceModelApi(currentModelId.value, modelFormData)
      ElMessage.success('设备型号已更新')
    } else {
      await createDeviceModelApi(modelFormData)
      ElMessage.success('设备型号已录入')
    }
    showModelDialog.value = false
    fetchModels()
  } finally {
    submitModelLoading.value = false
  }
}

async function handleDeleteModel(id: number) {
  try {
    await deleteDeviceModelApi(id)
    ElMessage.success('设备型号已删除')
    fetchModels()
  } catch (e) {
    //
  }
}

// -------------------------------------------------------------
// 设备菜单定制操作
// -------------------------------------------------------------
function getActiveSkuCount(row: any): number {
  if (!row.skus) return 0
  return row.skus.filter((s: any) => s.is_active && s.global_sku_is_active).length
}

async function openDeviceSkuDialog(row: any) {
  currentStoreItem.value = row
  editStoreItemBasePriceYuan.value = fenToYuan(row.base_price)
  showDeviceSkuDialog.value = true
  await fetchCurrentStoreItemSkus()
}

async function fetchCurrentStoreItemSkus() {
  if (!currentStoreItem.value) return
  loadingDeviceSkus.value = true
  try {
    const res = await getStoreItemSkusApi(currentStoreItem.value.id)
    if (res.data) {
      currentStoreItemSkus.value = (res.data || []).map((s: any) => {
        const globalDeltaFen = s.global_price_delta || 0
        const globalFinalFen = (currentStoreItem.value?.global_base_price || 0) + globalDeltaFen
        const minFinalFen = Math.floor(globalFinalFen * 0.8)
        const maxFinalFen = Math.floor(globalFinalFen * 1.2)
        const localBaseFen = currentStoreItem.value?.base_price || 0
        const minDeltaFen = minFinalFen - localBaseFen
        const maxDeltaFen = maxFinalFen - localBaseFen
        return {
          ...s,
          globalDeltaYuan: Number((globalDeltaFen / 100).toFixed(2)),
          minDeltaYuan: Number((minDeltaFen / 100).toFixed(2)),
          maxDeltaYuan: Number((maxDeltaFen / 100).toFixed(2)),
          editPriceDeltaYuan: Number(((s.price_delta || 0) / 100).toFixed(2)),
          statusLoading: false,
          priceLoading: false,
        }
      })
      currentStoreItem.value.skus = res.data
    }
  } finally {
    loadingDeviceSkus.value = false
  }
}

async function handleSaveStoreItemBasePrice() {
  if (!currentStoreItem.value) return
  const newBaseFen = yuanToFen(editStoreItemBasePriceYuan.value)
  try {
    await updateStoreMenuItemApi(currentStoreItem.value.id, {
      base_price: newBaseFen,
    })
    currentStoreItem.value.base_price = newBaseFen
    ElMessage.success(`基准价格已更新为 ¥${editStoreItemBasePriceYuan.value.toFixed(2)}`)
    // 联动更新每个 SKU 的允许加价范围
    if (currentStoreItemSkus.value) {
      currentStoreItemSkus.value.forEach((sku: any) => {
        const globalFinalFen = (currentStoreItem.value?.global_base_price || 0) + (sku.global_price_delta || 0)
        const minFinalFen = Math.floor(globalFinalFen * 0.8)
        const maxFinalFen = Math.floor(globalFinalFen * 1.2)
        sku.minDeltaYuan = Number(((minFinalFen - newBaseFen) / 100).toFixed(2))
        sku.maxDeltaYuan = Number(((maxFinalFen - newBaseFen) / 100).toFixed(2))
      })
    }
    fetchStoreMenuItems()
  } catch (e) {
    editStoreItemBasePriceYuan.value = fenToYuan(currentStoreItem.value.base_price)
  }
}

async function handleDeviceSkuPriceDeltaChange(sku: any) {
  if (!currentStoreItem.value) return
  sku.priceLoading = true
  try {
    const deltaFen = yuanToFen(sku.editPriceDeltaYuan)
    await updateStoreMenuSkuApi(sku.id, { price_delta: deltaFen })
    sku.price_delta = deltaFen
    sku.final_price = (currentStoreItem.value.base_price || 0) + deltaFen
    ElMessage.success(`规格 [${sku.template_name}] 分量加价已更新为 ¥${sku.editPriceDeltaYuan.toFixed(2)}`)
    fetchStoreMenuItems()
  } catch (e) {
    sku.editPriceDeltaYuan = Number(((sku.price_delta || 0) / 100).toFixed(2))
  } finally {
    sku.priceLoading = false
  }
}

async function handleToggleDeviceSkuStatus(sku: any, val: boolean) {
  sku.statusLoading = true
  try {
    await updateStoreMenuSkuApi(sku.id, { is_active: val })
    ElMessage.success(`规格 [${sku.template_name}] 已${val ? '供售' : '停售'}`)
    fetchStoreMenuItems()
  } catch (e: any) {
    sku.is_active = !val
  } finally {
    sku.statusLoading = false
  }
}

async function handleToggleStoreItemStatus(row: any) {
  row.statusLoading = true
  try {
    await updateStoreMenuItemApi(row.id, {
      is_active: row.is_active,
    })
    ElMessage.success(`商品 [${row.global_item_name}] 已${row.is_active ? '上架' : '下架'}`)
  } catch (e) {
    row.is_active = !row.is_active
  } finally {
    row.statusLoading = false
  }
}

async function handleSyncStoreMenu() {
  const currentStoreId = selectedMenuStore.value || authStore.selectedStoreId || (storeOptions.value[0]?.id)
  if (!currentStoreId) {
    ElMessage.warning('请先在下拉框选择要同步的门店')
    return
  }

  try {
    await syncStoreMenuApi(currentStoreId)
    ElMessage.success('设备/门店菜单已成功同步最新全局商品')
    fetchStoreMenuItems()
  } catch (e) {
    //
  }
}

// -------------------------------------------------------------
// 设备海报屏保操作
// -------------------------------------------------------------
function openCreatePosterDialog() {
  isEditPoster.value = false
  currentPosterId.value = null
  fetchStores()
  fetchDevices()
  Object.assign(posterFormData, {
    title: '',
    version: undefined,
    remarks: '',
    sort_order: 0,
    is_active: true,
    horizontal_image: '',
    vertical_image: '',
    banner_image: '',
    stores: [],
    devices: [],
    created_at: '',
    updated_at: '',
  })
  showPosterDialog.value = true
}

function openEditPosterDialog(row: PosterItem) {
  isEditPoster.value = true
  currentPosterId.value = row.id
  fetchStores()
  fetchDevices()
  Object.assign(posterFormData, {
    title: row.title,
    version: row.version,
    remarks: row.remarks || '',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
    horizontal_image: row.horizontal_image || '',
    vertical_image: row.vertical_image || '',
    banner_image: row.banner_image || '',
    stores: row.stores || [],
    devices: row.devices || [],
    created_at: row.created_at || '',
    updated_at: row.updated_at || '',
  })
  showPosterDialog.value = true
}

async function handleUploadPosterFile(fileObj: any, field: 'horizontal_image' | 'vertical_image' | 'banner_image') {
  const rawFile = fileObj.raw
  if (!rawFile) return

  try {
    ElMessage.info('正在上传海报图片素材...')
    const res = await uploadFileApi(rawFile, 'poster')
    const fileUrl = res.data?.url || (res.data as any)?.file_url
    if (fileUrl) {
      posterFormData[field] = fileUrl
      ElMessage.success('海报素材上传成功')
    }
  } catch (e) {
    // 错误拦截器已提示
  }
}

async function handleTogglePosterStatus(row: PosterItem) {
  try {
    await updatePosterApi(row.id, { is_active: row.is_active })
    ElMessage.success(`海报 [${row.title}] 状态已更新为：${row.is_active ? '启用' : '下架'}`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDeletePoster(id: number) {
  try {
    await deletePosterApi(id)
    ElMessage.success('海报配置已删除')
    fetchPosters()
  } catch (e) {
    // 错误拦截器已提示
  }
}

async function handleSubmitPoster() {
  if (!posterFormData.title || !posterFormData.title.trim()) {
    ElMessage.warning('请填写海报配置名称')
    return
  }

  const payload: any = {
    title: posterFormData.title.trim(),
    remarks: posterFormData.remarks || '',
    sort_order: posterFormData.sort_order || 0,
    is_active: posterFormData.is_active,
    horizontal_image: posterFormData.horizontal_image || '',
    vertical_image: posterFormData.vertical_image || '',
    banner_image: posterFormData.banner_image || '',
    stores: posterFormData.stores || [],
    devices: posterFormData.devices || [],
  }

  if (posterFormData.version) {
    payload.version = posterFormData.version
  }

  submitPosterLoading.value = true
  try {
    if (isEditPoster.value && currentPosterId.value) {
      await updatePosterApi(currentPosterId.value, payload)
      ElMessage.success('海报配置已成功更新')
    } else {
      await createPosterApi(payload)
      ElMessage.success('海报配置已成功创建')
    }
    showPosterDialog.value = false
    fetchPosters()
  } finally {
    submitPosterLoading.value = false
  }
}

// 监听路由 ?tab=xxx
watch(
  () => route.query.tab,
  (tab) => {
    if (tab && ['devices', 'models', 'menus', 'posters', 'stocks'].includes(tab as string)) {
      activeTab.value = tab as string
      if (tab === 'stocks') {
        fetchDeviceRecords()
      } else if (tab === 'menus') {
        fetchStoreMenuItems()
      }
    }
  },
  { immediate: true }
)

onMounted(() => {
  reloadAll()
})
</script>

<style scoped>
.device-tabs :deep(.el-tabs__header) {
  background-color: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.tab-label-box {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
  padding: 4px 6px;
}
.tab-icon {
  font-size: 16px;
}
.tab-badge :deep(.el-badge__content) {
  margin-top: 2px;
}
.guide-tip {
  margin-bottom: 16px;
  padding: 10px 16px;
  background-color: #ecf5ff;
  border-radius: 6px;
  color: #409eff;
  font-size: 13px;
  border: 1px solid #d9ecff;
}

/* 设备库存卡片样式 */
.barrel-stock-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  transition: all 0.2s;
}

.barrel-stock-item.is-low {
  background: #fffbe6;
  border-color: #ffe58f;
}

.barrel-stock-item.is-damaged {
  background: #fef0f0;
  border-color: #f56c6c;
}

.consumable-stock-item {
  background: #f4f4f5;
  border: 1px solid #e9e9eb;
  border-radius: 6px;
  padding: 10px 12px;
}

.consumable-stock-item.is-low {
  background: #fef0f0;
  border-color: #fde2e2;
}

/* 海报屏保表单样式 */
.form-section-card {
  border-radius: 8px;
  background-color: #fafafa;
}
.section-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.poster-upload-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #ffffff;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.upload-label {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
}
.upload-desc {
  font-size: 11px;
  color: #909399;
  margin-bottom: 8px;
}
.preview-container {
  display: flex;
  justify-content: center;
  align-items: center;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  background: #f8fafc;
  overflow: hidden;
  margin-bottom: 8px;
}
.horizontal-box {
  width: 180px;
  height: 100px;
}
.vertical-box {
  width: 100px;
  height: 130px;
}
.banner-box {
  width: 200px;
  height: 60px;
}
.preview-img {
  width: 100%;
  height: 100%;
}
.empty-tip {
  color: #c0c4cc;
  font-size: 12px;
}
.upload-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* 录入/编辑设备对话框样式 - 舒展简洁 */
.device-modal-form .form-section-card {
  background: #fbfcfe;
  border: 1px solid #eef2f7;
  border-radius: 8px;
  padding: 14px 18px 8px 18px;
  margin-bottom: 14px;
}
.device-modal-form .form-section-card:last-child {
  margin-bottom: 0;
}
.section-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.section-card-tag {
  width: 3px;
  height: 14px;
  background: #409eff;
  border-radius: 2px;
}
.section-card-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #1f2937;
}
.section-card-tip {
  font-size: 12px;
  color: #9ca3af;
  margin-left: 4px;
}
.device-modal-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.device-modal-form :deep(.el-form-item.mb-0) {
  margin-bottom: 4px;
}
.device-modal-form :deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 500;
  color: #4b5563;
  padding-bottom: 4px !important;
  line-height: 1.2;
}
.dialog-footer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

/* 门店菜单定制美化 */
.store-menu-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.store-menu-toolbar .toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.store-menu-toolbar .toolbar-right .count-tag {
  font-size: 13px;
  padding: 4px 10px;
}
.menu-product-cell {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 4px 0;
}
.menu-product-cell .product-avatar-wrapper {
  position: relative;
  width: 50px;
  height: 50px;
  flex-shrink: 0;
}
.menu-product-cell .product-avatar {
  width: 50px;
  height: 50px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.menu-product-cell .product-avatar-placeholder {
  width: 50px;
  height: 50px;
  border-radius: 8px;
  background-color: #f1f5f9;
  border: 1px dashed #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}
.menu-product-cell .detail-badge {
  position: absolute;
  bottom: -2px;
  right: -2px;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #ffffff;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}
.menu-product-cell .product-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  overflow: hidden;
}
.menu-product-cell .product-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.menu-product-cell .product-name {
  font-weight: 600;
  font-size: 14px;
  color: #1e293b;
  line-height: 1.3;
}
.menu-product-cell .category-tag {
  font-size: 11px;
  padding: 0 6px;
  height: 20px;
  line-height: 18px;
  border-radius: 4px;
}
.menu-product-cell .product-sub-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.menu-product-cell .product-id {
  color: #94a3b8;
  font-family: monospace;
}
.menu-product-cell .model-badge {
  color: #64748b;
  background-color: #f8fafc;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
  font-size: 11px;
}

/* 价格单元格 */
.store-price-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.store-price-main {
  display: inline-flex;
  align-items: baseline;
  color: #0f172a;
  font-weight: 600;
}
.store-currency-symbol {
  font-size: 12px;
  margin-right: 2px;
  color: #64748b;
}
.store-price-value {
  font-size: 15px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.store-price-sub {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

/* 规格胶囊列表 */
.sku-cell-wrapper {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sku-status-header {
  font-size: 12px;
  color: #64748b;
}
.sku-status-header .active-count {
  color: #10b981;
  font-weight: 600;
}
.sku-pills-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.store-sku-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 12px;
  font-size: 12px;
  background-color: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  cursor: pointer;
  transition: all 0.15s ease;
}
.store-sku-pill:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 5px rgba(16, 185, 129, 0.2);
}
.store-sku-pill.is-disabled {
  background-color: #f3f4f6;
  border-color: #e5e7eb;
  color: #9ca3af;
  text-decoration: line-through;
}
.store-sku-pill.is-global-off {
  background-color: #fef2f2;
  border-color: #fecaca;
  color: #dc2626;
}
.store-sku-pill .pill-delta {
  font-weight: 600;
  color: #ea580c;
  font-size: 11px;
  background-color: #fff7ed;
  border-radius: 8px;
  padding: 0 4px;
}
.store-sku-pill .pill-badge {
  font-size: 10px;
  padding: 0 4px;
  border-radius: 4px;
  line-height: 14px;
}
.store-sku-pill .pill-badge-pause {
  background-color: #fee2e2;
  color: #ef4444;
}
.store-sku-pill .pill-badge-off {
  background-color: #f3f4f6;
  color: #6b7280;
}
.sku-empty-wrapper .empty-text {
  font-size: 12px;
  color: #cbd5e1;
  font-style: italic;
}
</style>
