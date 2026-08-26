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
          <el-table-column prop="province" label="省份" width="100">
            <template #default="{ row }">{{ row.province || '-' }}</template>
          </el-table-column>
          <el-table-column prop="city" label="城市" width="100">
            <template #default="{ row }">{{ row.city || '-' }}</template>
          </el-table-column>
          <el-table-column prop="device_model_name" label="设备型号" width="130">
            <template #default="{ row }">
              <el-tag v-if="row.device_model_name" size="small" type="primary">{{ row.device_model_name }}</el-tag>
              <span v-else style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <StatusBadge :status="row.status" />
            </template>
          </el-table-column>
          <el-table-column prop="firmware_version" label="固件版本" width="110">
            <template #default="{ row }">{{ row.firmware_version || '-' }}</template>
          </el-table-column>
          <el-table-column label="经纬度坐标" width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.lng !== undefined && row.lng !== null && row.lat !== undefined && row.lat !== null" style="font-family: monospace; font-size: 12px;">
                {{ row.lng }}, {{ row.lat }}
              </span>
              <span v-else-if="row.gps_coordinate" style="font-family: monospace; font-size: 12px;">
                {{ row.gps_coordinate }}
              </span>
              <span v-else style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="last_heartbeat_at" label="最后心跳" width="170" />
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button type="success" link size="small" @click="viewDeviceStock(row.device_sn)">
                库存
              </el-button>
              <el-button type="primary" link size="small" @click="$router.push(`/monitor/${row.device_sn}`)">
                监控
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

        <el-form :inline="true" size="default" style="margin-bottom: 14px;">
          <el-form-item label="选择门店/设备归属">
            <el-select
              v-model="selectedMenuStore"
              placeholder="全部门店"
              clearable
              style="width: 240px;"
              @change="fetchStoreMenuItems"
            >
              <el-option
                v-for="s in storeOptions"
                :key="s.id"
                :label="`${s.name} (ID: ${s.id})`"
                :value="s.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Refresh" @click="fetchStoreMenuItems">
              查询
            </el-button>
            <el-button type="warning" plain icon="RefreshRight" @click="handleSyncStoreMenu">
              一键同步全局菜单
            </el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="loadingStoreItems" :data="storeItemList" stripe style="width: 100%">
          <el-table-column prop="id" label="门店商品ID" width="110" align="center" />
          <el-table-column prop="global_item_name" label="商品名称" min-width="160">
            <template #default="{ row }">
              <span style="font-weight: 600;">{{ row.global_item_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="global_category_name" label="所属分类" width="140" />
          <el-table-column label="基准全局售价(元)" width="150" align="right">
            <template #default="{ row }">
              <span style="color: #909399;">{{ formatCurrency(row.global_base_price) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="门店设备定价(元)" width="160">
            <template #default="{ row }">
              <el-input-number
                v-model="row.editPriceYuan"
                :min="0.01"
                :step="0.5"
                :precision="2"
                size="small"
                @blur="handleStoreItemPriceChange(row)"
              />
            </template>
          </el-table-column>
          <el-table-column label="可售规格定制" min-width="220">
            <template #default="{ row }">
              <div v-if="row.skus && row.skus.length > 0" style="display: flex; flex-direction: column; gap: 4px;">
                <div style="display: flex; align-items: center; justify-content: space-between;">
                  <span style="font-size: 12px; color: #606266;">
                    已启用 <strong>{{ getActiveSkuCount(row) }}</strong> / {{ row.skus.length }} 规格
                  </span>
                  <el-button type="primary" link size="small" @click="openDeviceSkuDialog(row)">
                    规格定制 &gt;
                  </el-button>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                  <el-tag
                    v-for="sku in row.skus"
                    :key="sku.id"
                    size="small"
                    :type="!sku.global_sku_is_active ? 'info' : (sku.is_active ? 'success' : 'danger')"
                    effect="plain"
                    style="cursor: pointer;"
                    @click="openDeviceSkuDialog(row)"
                  >
                    {{ sku.template_name }}
                    <span v-if="!sku.global_sku_is_active" style="font-size: 10px; color: #909399;">(全局关)</span>
                    <span v-else-if="!sku.is_active" style="font-size: 10px; color: #f56c6c;">(停用)</span>
                  </el-tag>
                </div>
              </div>
              <div v-else style="display: flex; align-items: center; justify-content: space-between;">
                <span style="color: #c0c4cc; font-size: 12px;">无规格</span>
                <el-button type="info" link size="small" @click="openDeviceSkuDialog(row)">
                  配置规格
                </el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="是否上架" width="120" align="center">
            <template #default="{ row }">
              <el-switch
                v-model="row.is_active"
                :loading="row.statusLoading"
                active-text="上架"
                inactive-text="下架"
                @change="handleToggleStoreItemStatus(row)"
              />
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
    <!-- 对话框 1: 录入/编辑设备档案 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showDeviceDialog"
      :title="isEditDevice ? '编辑设备档案配置' : '录入新设备档案'"
      width="680px"
    >
      <el-form :model="deviceFormData" label-width="130px">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="序列号 (SN)" required>
              <el-input v-model="deviceFormData.device_sn" :disabled="isEditDevice" placeholder="出厂唯一编码，如 SN001" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备名称" required>
              <el-input v-model="deviceFormData.device_name" placeholder="如 朝阳大悦城1号咖啡机" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="门店注册码 (key_code)">
              <el-input v-model="deviceFormData.key_code" placeholder="用于设备上线鉴权注册" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备状态">
              <el-select v-model="deviceFormData.status" style="width: 100%;">
                <el-option label="在线 (online)" value="online" />
                <el-option label="离线 (offline)" value="offline" />
                <el-option label="故障 (fault)" value="fault" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="分配所属门店">
              <el-select v-model="deviceFormData.store" placeholder="选择分配的门店" filterable clearable style="width: 100%;">
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
            <el-form-item label="硬件设备型号">
              <el-select v-model="deviceFormData.device_model" placeholder="选择硬件机型" clearable style="width: 100%;">
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

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="固件版本">
              <el-input v-model="deviceFormData.firmware_version" placeholder="如 1.0.0 或 2.1.4" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="静态资源版本">
              <el-input v-model="deviceFormData.resource_version" placeholder="如 0 或 101" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="MQTT Topic前缀">
          <el-input v-model="deviceFormData.mqtt_topic_prefix" placeholder="留空默认: automake/device/{SN}" />
        </el-form-item>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="所在省份">
              <el-input v-model="deviceFormData.province" placeholder="如 北京市、广东省" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所在城市">
              <el-input v-model="deviceFormData.city" placeholder="如 北京市、深圳市" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="经度 (lng)">
              <el-input-number v-model="deviceFormData.lng" :precision="6" :step="0.0001" placeholder="如 116.4074" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="纬度 (lat)">
              <el-input-number v-model="deviceFormData.lat" :precision="6" :step="0.0001" placeholder="如 39.9042" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="GPS 经纬度坐标">
          <el-input v-model="deviceFormData.gps_coordinate" placeholder="格式如：116.4074, 39.9042" />
        </el-form-item>

        <el-form-item label="设备详细布设地址">
          <el-input v-model="deviceFormData.address" placeholder="如 北京市朝阳区朝阳北路101号B1层中庭" />
        </el-form-item>

        <el-form-item label="扩展配置 (JSON)">
          <el-input
            v-model="deviceFormData.extra_config_raw"
            type="textarea"
            :rows="3"
            placeholder="例如: { &quot;cup_dispenser&quot;: 2, &quot;ice_module&quot;: true }"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDeviceDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitDeviceLoading" @click="handleSubmitDevice">
          确认保存
        </el-button>
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
      :title="`【${currentStoreItem?.global_item_name || '商品'}】设备可售规格定制`"
      width="820px"
    >
      <div class="guide-tip" style="margin-bottom: 14px;">
        💡 <strong>减法控制原则</strong>：当前设备可在全局启用的规格中自由选择<strong>启用或停用</strong>。若某规格在全局菜单中已被停用，则设备端无法单独开启（受全局控制，只能做减法）。
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div style="font-size: 13px; color: #606266;">
          所属商品：<strong style="color: #303133;">{{ currentStoreItem?.global_item_name }}</strong>
          （基准定价：<span style="color: #E6A23C; font-weight: bold;">{{ formatCurrency(currentStoreItem?.base_price) }}</span>）
        </div>
        <div>
          <el-button size="small" icon="Refresh" @click="fetchCurrentStoreItemSkus">
            刷新规格
          </el-button>
        </div>
      </div>

      <el-table v-loading="loadingDeviceSkus" :data="currentStoreItemSkus" size="small" stripe border style="width: 100%;">
        <el-table-column prop="global_sku_id" label="SKU ID" width="80" align="center">
          <template #default="{ row }">
            <el-tag type="info" size="small" effect="plain">#{{ row.global_sku_id }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="template_name" label="规格名称" width="120">
          <template #default="{ row }">
            <span style="font-weight: 600; color: #409EFF;">{{ row.template_name }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="template_category" label="规格分类" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.template_category || '-' }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="规格加价" width="100" align="right">
          <template #default="{ row }">
            <span :style="{ color: row.price_delta > 0 ? '#E6A23C' : '#67C23A', fontWeight: '500' }">
              {{ row.price_delta > 0 ? `+${formatCurrency(row.price_delta)}` : '¥0.00' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="设备总售价" width="110" align="right">
          <template #default="{ row }">
            <span style="font-weight: bold; color: #E6A23C;">
              {{ formatCurrency(row.final_price || ((currentStoreItem?.base_price || 0) + (row.price_delta || 0))) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="生效配料用量" min-width="180">
          <template #default="{ row }">
            <div v-if="row.effective_ingredients && row.effective_ingredients.length > 0" style="display: flex; flex-wrap: wrap; gap: 4px;">
              <el-tag
                v-for="(ing, idx) in row.effective_ingredients"
                :key="idx"
                size="small"
                type="info"
                effect="plain"
              >
                {{ ing.material }}: {{ ing.quantity }}{{ ing.unit }}
              </el-tag>
            </div>
            <span v-else style="color: #c0c4cc; font-size: 11px;">无额外消耗</span>
          </template>
        </el-table-column>

        <el-table-column label="全局状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.global_sku_is_active" size="small" type="success" effect="dark">
              全局启用
            </el-tag>
            <el-tag v-else size="small" type="info" effect="plain">
              全局已停用
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="本设备状态" width="130" align="center">
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

const deviceFormData = reactive({
  device_sn: '',
  device_name: '',
  key_code: '',
  status: 'offline',
  store: undefined as number | undefined | null,
  device_model: undefined as number | undefined | null,
  province: '',
  city: '',
  lat: null as number | null,
  lng: null as number | null,
  firmware_version: '',
  resource_version: 0,
  mqtt_topic_prefix: '',
  gps_coordinate: '',
  address: '',
  extra_config_raw: '',
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
const showDeviceSkuDialog = ref(false)
const currentStoreItem = ref<StoreMenuItem | null>(null)
const currentStoreItemSkus = ref<StoreMenuSku[]>([])
const loadingDeviceSkus = ref(false)

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
    lat: null,
    lng: null,
    firmware_version: '',
    resource_version: 0,
    mqtt_topic_prefix: '',
    gps_coordinate: '',
    address: '',
    extra_config_raw: '',
  })
  showDeviceDialog.value = true
}

function openEditDeviceDialog(row: DeviceItem) {
  isEditDevice.value = true
  currentDeviceSn.value = row.device_sn
  Object.assign(deviceFormData, {
    device_sn: row.device_sn,
    device_name: row.device_name,
    key_code: row.key_code || '',
    status: row.status,
    store: row.store,
    device_model: row.device_model,
    province: row.province || '',
    city: row.city || '',
    lat: row.lat !== undefined && row.lat !== null ? Number(row.lat) : null,
    lng: row.lng !== undefined && row.lng !== null ? Number(row.lng) : null,
    firmware_version: row.firmware_version || '',
    resource_version: row.resource_version || 0,
    mqtt_topic_prefix: row.mqtt_topic_prefix || '',
    gps_coordinate: row.gps_coordinate || '',
    address: row.address || '',
    extra_config_raw: row.extra_config ? JSON.stringify(row.extra_config, null, 2) : '',
  })
  showDeviceDialog.value = true
}

async function handleSubmitDevice() {
  if (!deviceFormData.device_sn || !deviceFormData.device_name) {
    ElMessage.warning('设备序列号和设备名称为必填项')
    return
  }

  let extraConfigObj = null
  if (deviceFormData.extra_config_raw && deviceFormData.extra_config_raw.trim()) {
    try {
      extraConfigObj = JSON.parse(deviceFormData.extra_config_raw)
    } catch (err) {
      ElMessage.error('扩展配置 JSON 格式错误，请检查')
      return
    }
  }

  const payload: any = {
    device_sn: deviceFormData.device_sn,
    device_name: deviceFormData.device_name,
    key_code: deviceFormData.key_code || '',
    status: deviceFormData.status,
    store: deviceFormData.store || null,
    device_model: deviceFormData.device_model || null,
    province: deviceFormData.province || '',
    city: deviceFormData.city || '',
    lat: deviceFormData.lat !== null && deviceFormData.lat !== undefined ? deviceFormData.lat : null,
    lng: deviceFormData.lng !== null && deviceFormData.lng !== undefined ? deviceFormData.lng : null,
    firmware_version: deviceFormData.firmware_version || '',
    resource_version: Number(deviceFormData.resource_version) || 0,
    mqtt_topic_prefix: deviceFormData.mqtt_topic_prefix || '',
    gps_coordinate: deviceFormData.gps_coordinate || '',
    address: deviceFormData.address || '',
    extra_config: extraConfigObj || {},
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
  showDeviceSkuDialog.value = true
  await fetchCurrentStoreItemSkus()
}

async function fetchCurrentStoreItemSkus() {
  if (!currentStoreItem.value) return
  loadingDeviceSkus.value = true
  try {
    const res = await getStoreItemSkusApi(currentStoreItem.value.id)
    if (res.data) {
      currentStoreItemSkus.value = (res.data || []).map((s: any) => ({
        ...s,
        statusLoading: false,
      }))
      currentStoreItem.value.skus = res.data
    }
  } finally {
    loadingDeviceSkus.value = false
  }
}

async function handleToggleDeviceSkuStatus(sku: any, val: boolean) {
  sku.statusLoading = true
  try {
    await updateStoreMenuSkuApi(sku.id, { is_active: val })
    ElMessage.success(`规格 [${sku.template_name}] 已${val ? '启用' : '停用'}`)
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

async function handleStoreItemPriceChange(row: any) {
  try {
    const priceFen = yuanToFen(row.editPriceYuan)
    await updateStoreMenuItemApi(row.id, {
      base_price: priceFen,
    })
    ElMessage.success(`商品 [${row.global_item_name}] 售价已更新为 ¥${row.editPriceYuan.toFixed(2)}`)
  } catch (e) {
    fetchStoreMenuItems()
  }
}

async function handleSyncStoreMenu() {
  const currentStoreId = authStore.selectedStoreId || authStore.user?.stores[0]?.id
  if (!currentStoreId) {
    ElMessage.warning('请先在顶部选择要同步的门店')
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
</style>
