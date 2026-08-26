<template>
  <div class="page-container menu-management-page">
    <PageHeader
      title="全局菜单档案管理"
      subtitle="集中维护标准菜谱商品、规格模板库与品类分类，支持平行业务联动与一站式高效配置"
    >
      <template #actions>
        <el-button v-if="activeTab === 'items'" type="primary" icon="Plus" @click="openCreateItemDialog">
          + 新建全局商品
        </el-button>
        <el-button v-else-if="activeTab === 'skus'" type="primary" icon="Refresh" @click="fetchSkus">
          刷新规格库
        </el-button>
        <el-button v-else-if="activeTab === 'templates'" type="primary" icon="Plus" @click="openCreateTemplateDialog">
          + 新建规格模板
        </el-button>
        <el-button v-else-if="activeTab === 'categories'" type="primary" icon="Plus" @click="openCreateCategoryDialog">
          + 新建品类分类
        </el-button>
      </template>
    </PageHeader>

    <!-- 顶部平行选项卡 -->
    <el-tabs v-model="activeTab" type="border-card" class="menu-tabs" @tab-change="handleTabChange">
      <!-- ============================================================ -->
      <!-- TAB 1: 全局菜谱商品 (GlobalMenuItem) -->
      <!-- ============================================================ -->
      <el-tab-pane name="items">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">☕</span>
            <span>全局菜谱商品</span>
            <el-badge :value="itemList.length" type="primary" class="tab-badge" />
          </div>
        </template>

        <!-- 筛选条件 -->
        <el-form :inline="true" size="default" style="margin-bottom: 14px;">
          <el-form-item label="所属菜单分类">
            <el-select
              v-model="selectedCategory"
              placeholder="全部分类"
              clearable
              style="width: 220px;"
              @change="fetchItems"
            >
              <el-option
                v-for="c in categoryList"
                :key="c.id"
                :label="`${c.name} (${c.device_model_name || '机型'})`"
                :value="c.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="商品名称">
            <el-input v-model="itemSearchKeyword" placeholder="输入商品名称" clearable />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchItems">查询</el-button>
          </el-form-item>
        </el-form>

        <!-- 商品大表 -->
        <el-table v-loading="loadingItems" :data="itemList" stripe style="width: 100%">
          <el-table-column prop="id" label="ID" width="65" align="center" />

          <el-table-column label="商品主图" width="80" align="center">
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                fit="cover"
                preview-teleported
                style="width: 44px; height: 44px; border-radius: 4px; border: 1px solid #ebeef5; cursor: pointer;"
              />
              <span v-else style="color: #c0c4cc; font-size: 11px;">无主图</span>
            </template>
          </el-table-column>

          <el-table-column label="详情页图" width="80" align="center">
            <template #default="{ row }">
              <el-image
                v-if="row.detail_page"
                :src="row.detail_page"
                :preview-src-list="[row.detail_page]"
                fit="cover"
                preview-teleported
                style="width: 44px; height: 44px; border-radius: 4px; border: 1px solid #ebeef5; cursor: pointer;"
              />
              <span v-else style="color: #c0c4cc; font-size: 11px;">无详情图</span>
            </template>
          </el-table-column>

          <el-table-column prop="name" label="商品名称" min-width="140" />

          <el-table-column prop="category_name" label="所属分类" min-width="130">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ row.category_name }}</el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="device_model_name" label="适配机型" width="130">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.device_model_name || '-' }}</el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="base_price" label="基准售价" width="110">
            <template #default="{ row }">
              <span style="font-weight: bold; color: #E6A23C;">
                {{ formatCurrency(row.base_price) }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="挂载规格 (SKU)" min-width="260">
            <template #default="{ row }">
              <div v-if="row.skus && row.skus.length > 0" style="display: flex; flex-wrap: wrap; gap: 4px;">
                <el-tag
                  v-for="sku in row.skus"
                  :key="sku.id"
                  size="small"
                  :type="sku.is_active ? 'primary' : 'info'"
                  effect="plain"
                >
                  {{ sku.template_name || sku.name }}
                  <span v-if="sku.price_delta > 0" style="color: #E6A23C; font-weight: 600;">
                    (+{{ formatCurrency(sku.price_delta) }})
                  </span>
                </el-tag>
              </div>
              <span v-else style="color: #909399; font-size: 12px;">未配置规格</span>
            </template>
          </el-table-column>

          <el-table-column prop="sort_order" label="排序" width="75" align="center" sortable />

          <el-table-column label="上架状态" width="95" align="center">
            <template #default="{ row }">
              <el-switch v-model="row.is_active" @change="handleToggleItemStatus(row)" />
            </template>
          </el-table-column>

          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openEditItemDialog(row)">
                编辑档案/规格
              </el-button>
              <el-button type="warning" link size="small" @click="openRecipeModal(row)">
                定制配方
              </el-button>
              <el-popconfirm title="确定删除该全局商品吗？" @confirm="handleDeleteItem(row.id)">
                <template #reference>
                  <el-button type="danger" link size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 2: 菜单规格库 (GlobalMenuSku) - 实体规格与配方全览 -->
      <!-- ============================================================ -->
      <el-tab-pane name="skus">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">✨</span>
            <span>菜单规格库</span>
            <el-badge :value="skuList.length" type="warning" class="tab-badge" />
          </div>
        </template>

        <div class="guide-tip" style="margin-bottom: 14px;">
          💡 说明：本页面汇总了所有商品已挂载的具体规格实体。每个具体商品的规格均拥有<strong>独立的唯一 SKU ID</strong> 与<strong>生效配料用量</strong>。
          添加商品时默认会继承规格模板的标准配料，您也可以点击“配料调整”为该商品的指定规格定制专属配方或点击“重置为模板配方”。
        </div>

        <!-- 筛选条件 -->
        <el-form :inline="true" size="default" style="margin-bottom: 14px;">
          <el-form-item label="所属商品">
            <el-select
              v-model="filterSkuItem"
              placeholder="全部商品"
              clearable
              filterable
              style="width: 180px;"
              @change="fetchSkus"
            >
              <el-option
                v-for="item in itemList"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="商品分类">
            <el-select
              v-model="filterSkuCategory"
              placeholder="全部分类"
              clearable
              style="width: 160px;"
              @change="fetchSkus"
            >
              <el-option
                v-for="c in categoryList"
                :key="c.id"
                :label="`${c.name} (${c.device_model_name || '机型'})`"
                :value="c.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="规格分类">
            <el-select
              v-model="filterSkuTemplateCat"
              placeholder="全部规格分类"
              clearable
              style="width: 140px;"
              @change="fetchSkus"
            >
              <el-option label="杯型" value="杯型" />
              <el-option label="温度" value="温度" />
              <el-option label="糖度" value="糖度" />
              <el-option label="风味" value="风味" />
              <el-option label="通用/默认" value="default" />
            </el-select>
          </el-form-item>

          <el-form-item label="关键字">
            <el-input v-model="skuSearchKeyword" placeholder="商品名或规格名" clearable style="width: 180px;" />
          </el-form-item>

          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchSkus">查询</el-button>
            <el-button icon="Refresh" @click="fetchSkus">刷新</el-button>
          </el-form-item>
        </el-form>

        <!-- 规格大表 -->
        <el-table v-loading="loadingSkus" :data="skuList" stripe style="width: 100%">
          <el-table-column prop="id" label="SKU ID" width="90" align="center">
            <template #default="{ row }">
              <el-tag type="info" size="small" effect="plain" style="font-weight: bold;">
                #{{ row.id }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="item_name" label="所属商品" min-width="150">
            <template #default="{ row }">
              <span style="font-weight: 600;">{{ row.item_name }}</span>
              <el-tag v-if="row.item_category_name" size="small" type="info" style="margin-left: 6px;">
                {{ row.item_category_name }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="template_name" label="规格名称" width="120">
            <template #default="{ row }">
              <span style="font-weight: 600; color: #409EFF;">{{ row.template_name }}</span>
            </template>
          </el-table-column>

          <el-table-column prop="template_category" label="规格分类" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="getCategoryTag(row.template_category)" size="small">
                {{ row.template_category }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="商品基准价" width="110" align="right">
            <template #default="{ row }">
              <span style="color: #909399;">{{ formatCurrency(row.item_base_price) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="规格加价" width="110" align="right">
            <template #default="{ row }">
              <span :style="{ fontWeight: '600', color: row.price_delta > 0 ? '#E6A23C' : '#67C23A' }">
                {{ row.price_delta > 0 ? `+${formatCurrency(row.price_delta)}` : '¥0.00' }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="叠加总售价" width="120" align="right">
            <template #default="{ row }">
              <span style="font-weight: bold; color: #E6A23C; font-size: 14px;">
                {{ formatCurrency(row.final_price || ((row.item_base_price || 0) + (row.price_delta || 0))) }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="生效配料用量 (配方)" min-width="260">
            <template #default="{ row }">
              <div style="margin-bottom: 4px;">
                <el-tag v-if="row.is_custom_recipe" size="small" type="warning" effect="dark">
                  专属定制配方
                </el-tag>
                <el-tag v-else size="small" type="success" effect="plain">
                  继承模板配方
                </el-tag>
              </div>
              <div v-if="row.effective_ingredients && row.effective_ingredients.length > 0" style="display: flex; flex-wrap: wrap; gap: 4px;">
                <el-tag
                  v-for="(ing, idx) in row.effective_ingredients"
                  :key="idx"
                  size="small"
                  :type="ing.is_custom ? 'warning' : 'info'"
                  effect="plain"
                >
                  {{ ing.material }}: {{ ing.quantity }}{{ ing.unit }}
                </el-tag>
              </div>
              <span v-else style="color: #c0c4cc; font-size: 12px;">无配料消耗</span>
            </template>
          </el-table-column>

          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-switch v-model="row.is_active" @change="handleToggleSkuStatus(row)" />
            </template>
          </el-table-column>

          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openEditSkuRecipeDialog(row)">
                配料调整
              </el-button>
              <el-popconfirm
                v-if="row.is_custom_recipe"
                title="确定清除专属定制配料并重置为模板默认配料吗？"
                @confirm="handleResetSkuRecipe(row)"
              >
                <template #reference>
                  <el-button type="warning" link size="small">重置为模板</el-button>
                </template>
              </el-popconfirm>
              <el-button type="info" link size="small" @click="openEditSkuPriceDialog(row)">
                改价/排序
              </el-button>
              <el-popconfirm title="确定从该商品移除此规格吗？" @confirm="handleDeleteSku(row.id)">
                <template #reference>
                  <el-button type="danger" link size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 3: 规格模板库 (GlobalSkuTemplate) -->
      <!-- ============================================================ -->
      <el-tab-pane name="templates">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">📐</span>
            <span>规格模板库</span>
            <el-badge :value="templateList.length" type="warning" class="tab-badge" />
          </div>
        </template>

        <el-form :inline="true" size="default" style="margin-bottom: 14px;">
          <el-form-item label="规格分类">
            <el-select
              v-model="filterTemplateCategory"
              placeholder="全部分类"
              clearable
              style="width: 160px;"
              @change="fetchTemplates"
            >
              <el-option label="杯型" value="杯型" />
              <el-option label="温度" value="温度" />
              <el-option label="糖度" value="糖度" />
              <el-option label="风味" value="风味" />
              <el-option label="通用/默认" value="default" />
            </el-select>
          </el-form-item>
          <el-form-item label="规格名称">
            <el-input v-model="templateSearchKeyword" placeholder="输入规格名称或描述" clearable />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchTemplates">查询</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="loadingTemplates" :data="templateList" stripe style="width: 100%">
          <el-table-column prop="id" label="ID" width="70" align="center" />
          <el-table-column prop="category" label="规格分类" width="130">
            <template #default="{ row }">
              <el-tag :type="getCategoryTag(row.category)" size="small">
                {{ row.category }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="规格名称" min-width="150">
            <template #default="{ row }">
              <span style="font-weight: 600;">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="default_price_delta" label="默认加价(元)" width="140">
            <template #default="{ row }">
              <span
                :style="{
                  fontWeight: 'bold',
                  color: row.default_price_delta > 0 ? '#E6A23C' : '#67C23A'
                }"
              >
                {{ row.default_price_delta > 0 ? `+${formatCurrency(row.default_price_delta)}` : '¥0.00' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="规格默认配料消耗" min-width="240">
            <template #default="{ row }">
              <div v-if="row.ingredients && row.ingredients.length > 0" style="display: flex; flex-wrap: wrap; gap: 4px;">
                <el-tag
                  v-for="(ing, idx) in row.ingredients"
                  :key="idx"
                  size="small"
                  type="info"
                  effect="plain"
                >
                  {{ ing.material_name || ing.material }}: {{ ing.quantity }}{{ ing.unit || 'g' }}
                </el-tag>
              </div>
              <span v-else style="color: #c0c4cc; font-size: 12px;">无默认配料</span>
            </template>
          </el-table-column>
          <el-table-column prop="sku_count" label="绑定商品数" width="110" align="center">
            <template #default="{ row }">
              <el-badge :value="row.sku_count || 0" type="primary" />
            </template>
          </el-table-column>
          <el-table-column prop="description" label="规格描述" min-width="150" show-overflow-tooltip />
          <el-table-column prop="sort_order" label="排序" width="80" align="center" sortable />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-switch v-model="row.is_active" @change="handleToggleTemplateStatus(row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openEditTemplateDialog(row)">
                编辑
              </el-button>
              <el-popconfirm title="确定删除该规格模板吗？" @confirm="handleDeleteTemplate(row.id)">
                <template #reference>
                  <el-button type="danger" link size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 3: 菜单品类分类 (GlobalMenuCategory) -->
      <!-- ============================================================ -->
      <el-tab-pane name="categories">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">📂</span>
            <span>菜单品类分类</span>
            <el-badge :value="categoryList.length" type="success" class="tab-badge" />
          </div>
        </template>

        <el-form :inline="true" size="default" style="margin-bottom: 14px;">
          <el-form-item label="按硬件机型筛选">
            <el-select
              v-model="selectedCategoryModel"
              placeholder="全部设备型号"
              clearable
              style="width: 200px;"
              @change="fetchCategories"
            >
              <el-option
                v-for="m in modelOptions"
                :key="m.id"
                :label="`${m.name} (${m.code})`"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchCategories">查询</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="loadingCategories" :data="categoryList" stripe style="width: 100%">
          <el-table-column prop="id" label="ID" width="80" align="center" />
          <el-table-column prop="name" label="分类名称" min-width="160" />
          <el-table-column prop="device_model_name" label="归属设备机型" min-width="160">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ row.device_model_name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="label" label="特色标签" width="130">
            <template #default="{ row }">
              <el-tag v-if="row.label === 'recomm'" size="small" type="danger">★ 店长推荐</el-tag>
              <el-tag v-else-if="row.label === 'hot'" size="small" type="warning">🔥 畅销爆款</el-tag>
              <el-tag v-else-if="row.label === 'new'" size="small" type="success">✨ 尝鲜新品</el-tag>
              <el-tag v-else size="small" type="info">{{ row.label || '常规' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sort_order" label="排序权重" width="110" align="center" sortable />
          <el-table-column prop="item_count" label="归属商品数" width="120" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="primary">{{ row.item_count || 0 }} 款</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用状态" width="110" align="center">
            <template #default="{ row }">
              <el-switch v-model="row.is_active" @change="handleToggleCategoryStatus(row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openEditCategoryDialog(row)">
                编辑
              </el-button>
              <el-popconfirm title="确定删除该分类吗？" @confirm="handleDeleteCategory(row.id)">
                <template #reference>
                  <el-button type="danger" link size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- ============================================================ -->
    <!-- 对话框 1: 新建/编辑全局商品 (含内联规格与累加计算) -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showItemDialog"
      :title="isEditItem ? `编辑全局商品档案 (ID: ${currentItemId})` : '新建全局商品档案'"
      width="900px"
      top="3vh"
      :close-on-click-modal="false"
    >
      <el-form :model="itemFormData" label-position="top">
        <!-- 分区 1: 基本档案与定价 -->
        <el-card shadow="never" class="form-section-card">
          <template #header>
            <span class="section-title">📋 基本档案与定价</span>
          </template>

          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="商品名称" required>
                <el-input v-model="itemFormData.name" placeholder="如 经典美式、生椰拿铁" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="所属菜单分类" required>
                <el-select v-model="itemFormData.category" placeholder="请选择分类" style="width: 100%;">
                  <el-option
                    v-for="c in categoryList"
                    :key="c.id"
                    :label="`${c.name} (${c.device_model_name || '机型'})`"
                    :value="c.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="全局基准售价 (元)" required>
                <el-input-number
                  v-model="itemFormData.priceYuan"
                  :min="0.01"
                  :step="1"
                  :precision="2"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="排序权重">
                <el-input-number v-model="itemFormData.sort_order" :min="0" :max="999" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="是否上架">
                <el-switch v-model="itemFormData.is_active" active-text="上架" inactive-text="下架" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="主要原料说明 (原料卡片展示)">
            <el-input
              v-model="itemFormData.main_ingredients"
              type="textarea"
              :rows="2"
              placeholder="请输入主要原料说明（如：优质新鲜赣南脐橙、纯净冰块、天然果糖）"
            />
          </el-form-item>

          <el-form-item label="商品说明">
            <el-input
              v-model="itemFormData.price_description"
              type="textarea"
              :rows="2"
              placeholder="请输入商品说明（如：阳光黄金脐橙整颗冷榨，不加一滴水与蔗糖，建议30分钟内饮用口感最佳）"
            />
          </el-form-item>
        </el-card>

        <!-- 分区 2: 商品主图与详情页海报 -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <span class="section-title">🖼 商品图片与详情页海报</span>
          </template>

          <el-row :gutter="20">
            <!-- 主图 -->
            <el-col :span="12">
              <div class="image-upload-box">
                <div class="box-title">商品主图 (点单大图)</div>
                <div class="box-sub" style="font-size: 12px; color: #909399; margin-bottom: 6px;">
                  推荐尺寸：1:1 正方形 (如 800×800px)，大小 &lt; 2MB
                </div>
                <div class="img-preview square-box">
                  <el-image v-if="itemFormData.image_url" :src="itemFormData.image_url" fit="cover" class="preview-inner" />
                  <div v-else class="empty-txt">暂无主图</div>
                </div>
                <div class="btn-group">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    accept="image/png,image/jpeg,image/jpg,image/webp"
                    :on-change="(file: any) => handleUploadImage(file, 'image_url')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传主图</el-button>
                  </el-upload>
                  <el-button v-if="itemFormData.image_url" size="small" type="danger" link @click="itemFormData.image_url = ''">
                    清空
                  </el-button>
                </div>
                <el-input v-model="itemFormData.image_url" size="small" placeholder="或直接输入主图 URL" style="margin-top: 8px;" />
              </div>
            </el-col>

            <!-- 详情页海报 -->
            <el-col :span="12">
              <div class="image-upload-box">
                <div class="box-title">商品详情页图 (detail_page)</div>
                <div class="box-sub" style="font-size: 12px; color: #e6a23c; margin-bottom: 6px; font-weight: 500;">
                  严格规范：宽必须为 750px (如 750×1334px)，大小 &lt; 1MB
                </div>
                <div class="img-preview detail-box">
                  <el-image v-if="itemFormData.detail_page" :src="itemFormData.detail_page" fit="contain" class="preview-inner" />
                  <div v-else class="empty-txt">暂无详情图</div>
                </div>
                <div class="btn-group">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    accept="image/png,image/jpeg,image/jpg,image/webp"
                    :on-change="(file: any) => handleUploadImage(file, 'detail_page')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传详情图</el-button>
                  </el-upload>
                  <el-button v-if="itemFormData.detail_page" size="small" type="danger" link @click="itemFormData.detail_page = ''">
                    清空
                  </el-button>
                </div>
                <el-input v-model="itemFormData.detail_page" size="small" placeholder="或直接输入详情页图 URL" style="margin-top: 8px;" />
              </div>
            </el-col>
          </el-row>
        </el-card>

        <!-- 分区 3: 挂载规格与定价 (GlobalSkuTemplate 映射子表) -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <span class="section-title">🏷 挂载商品规格与定价 (GlobalSkuTemplate 映射)</span>
                <span style="color: #909399; font-size: 12px; margin-left: 8px;">
                  选择该商品支持的规格，并在右侧直接调整专属加价（叠加计算基于当前最新值）
                </span>
              </div>
              <div style="display: flex; gap: 8px;">
                <el-button type="success" plain size="small" icon="Plus" @click="openCreateTemplateDialog">
                  + 新建规格模板
                </el-button>
                <el-button type="primary" size="small" icon="Plus" @click="handleAddSkuRow">
                  + 添加规格
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="itemFormData.skus.length === 0" style="text-align: center; color: #909399; padding: 20px 0;">
            暂未挂载任何规格模板，请点击右上角“+ 添加规格”选择规格
          </div>

          <el-table v-else :data="itemFormData.skus" size="small" border style="width: 100%">
            <!-- 展开配置此规格的用料配方 -->
            <el-table-column type="expand">
              <template #default="{ row }">
                <div style="padding: 10px 14px; background-color: #f8f9fb; border-radius: 6px;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-weight: 600; font-size: 13px; color: #303133;">
                      🧪 规格 [{{ row.template_name || '未选模板' }}] 专属用料配方
                    </span>
                    <div style="display: flex; gap: 8px;">
                      <el-button size="small" type="primary" link @click="handleAddRowIngredient(row)">
                        + 添加用料
                      </el-button>
                      <el-button size="small" type="warning" link @click="handleResetRowIngredientToTemplate(row)">
                        恢复模板默认用料
                      </el-button>
                    </div>
                  </div>

                  <div v-if="!row.ingredients || row.ingredients.length === 0" style="color: #909399; font-size: 12px; padding: 6px 0;">
                    暂无配料消耗（点击右上角“+ 添加用料”配置该规格原料）
                  </div>

                  <el-table v-else :data="row.ingredients" size="small" border style="width: 100%;">
                    <el-table-column label="物料名称" min-width="160">
                      <template #default="{ row: ing }">
                        <el-select
                          v-model="ing.material"
                          placeholder="选择物料"
                          filterable
                          size="small"
                          style="width: 100%;"
                          @change="(val: string) => handleRecipeMaterialSelect(ing, val)"
                        >
                          <el-option
                            v-for="m in materialOptions"
                            :key="m.name"
                            :label="`${m.name} (${m.code}) - ${m.unit}`"
                            :value="m.name"
                          />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column label="消耗用量" width="130">
                      <template #default="{ row: ing }">
                        <el-input-number v-model="ing.quantity" :min="0.01" :step="1" :precision="2" size="small" style="width: 100%;" />
                      </template>
                    </el-table-column>
                    <el-table-column label="单位" width="100">
                      <template #default="{ row: ing }">
                        <el-input v-model="ing.unit" size="small" placeholder="单位" />
                      </template>
                    </el-table-column>
                    <el-table-column label="操作" width="70" align="center">
                      <template #default="{ $index: ingIndex }">
                        <el-button type="danger" link size="small" @click="row.ingredients.splice(ingIndex, 1)">
                          删除
                        </el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </template>
            </el-table-column>

            <!-- 规格选择 -->
            <el-table-column label="选择规格模板 (GlobalSkuTemplate)" min-width="220">
              <template #default="{ row }">
                <el-select
                  v-model="row.template"
                  placeholder="选择规格模板"
                  filterable
                  style="width: 100%;"
                  @change="(val: any) => handleSkuTemplateSelect(row, val)"
                >
                  <el-option
                    v-for="t in templateList"
                    :key="t.id"
                    :label="`[${t.category}] ${t.name} (默认+${formatCurrency(t.default_price_delta)})`"
                    :value="t.id"
                    :disabled="isTemplateAlreadySelected(row, t.id)"
                  />
                </el-select>
              </template>
            </el-table-column>

            <!-- 规格分类 -->
            <el-table-column label="分类" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.template_category || '-' }}</el-tag>
              </template>
            </el-table-column>

            <!-- 默认加价 -->
            <el-table-column label="模板默认加价" width="110" align="center">
              <template #default="{ row }">
                <span style="color: #909399;">
                  +{{ formatCurrency(row.default_price_delta || 0) }}
                </span>
              </template>
            </el-table-column>

            <!-- 商品专属加价 (可编辑) -->
            <el-table-column label="本商品加价 (元)" width="150" align="center">
              <template #default="{ row }">
                <el-input-number
                  v-model="row.priceDeltaYuan"
                  :min="-999"
                  :step="0.5"
                  :precision="2"
                  size="small"
                  style="width: 100%;"
                />
              </template>
            </el-table-column>

            <!-- 计算后叠加最新售价 (加当前最新值) -->
            <el-table-column label="叠加后最新售价" width="130" align="center">
              <template #default="{ row, $index }">
                <div style="font-weight: bold; color: #E6A23C; font-size: 13px;">
                  ¥{{ getAccumulatedPrice($index) }}
                </div>
                <div style="font-size: 10px; color: #909399;">
                  (前值 + ¥{{ Number(row.priceDeltaYuan || 0).toFixed(2) }})
                </div>
              </template>
            </el-table-column>

            <!-- 状态 -->
            <el-table-column label="启用" width="75" align="center">
              <template #default="{ row }">
                <el-switch v-model="row.is_active" size="small" />
              </template>
            </el-table-column>

            <!-- 操作 -->
            <el-table-column label="操作" width="75" align="center">
              <template #default="{ $index }">
                <el-button type="danger" link size="small" @click="itemFormData.skus.splice($index, 1)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 底部叠加汇总 -->
          <div v-if="itemFormData.skus.length > 0" class="sku-summary-bar">
            <div class="summary-item">
              基准售价: <strong>¥{{ Number(itemFormData.priceYuan || 0).toFixed(2) }}</strong>
            </div>
            <div class="summary-item">
              + 规格累计加价: <strong style="color: #E6A23C;">{{ getTotalDeltaPrice() }} 元</strong>
            </div>
            <div class="summary-item total">
              叠加后最终总售价: <strong>¥{{ getTotalCombinedPrice() }}</strong>
            </div>
          </div>
        </el-card>
      </el-form>

      <template #footer>
        <el-button @click="showItemDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitItemLoading" @click="handleSubmitItem">
          确认保存商品与规格
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 2: 新建/编辑规格模板 (GlobalSkuTemplate) -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showTemplateDialog"
      :title="isEditTemplate ? `编辑规格模板 (ID: ${currentTemplateId})` : '新建全局规格模板'"
      width="680px"
      top="5vh"
    >
      <el-form :model="templateFormData" label-position="top">
        <el-card shadow="never" class="form-section-card">
          <template #header>
            <span class="section-title">📌 模板基本信息</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="规格分类" required>
                <div style="display: flex; gap: 8px; width: 100%;">
                  <el-select
                    v-model="templateFormData.category"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="选择已有分类或输入新分类"
                    style="flex: 1;"
                    @blur="handleCategorySelectBlur"
                  >
                    <el-option
                      v-for="cat in availableTemplateCategories"
                      :key="cat"
                      :label="cat"
                      :value="cat"
                    >
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span>{{ cat }}</span>
                        <el-tag size="small" type="info" effect="plain" style="margin-left: 8px;">分类</el-tag>
                      </div>
                    </el-option>
                  </el-select>
                  <el-button
                    type="primary"
                    plain
                    icon="Plus"
                    @click="handlePromptNewCategory"
                  >
                    新建分类
                  </el-button>
                </div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="规格名称" required>
                <el-input v-model="templateFormData.name" placeholder="如 大杯、热、去冰、五分糖" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="默认加价 (元)">
                <el-input-number
                  v-model="templateFormData.priceYuan"
                  :min="-999"
                  :step="0.5"
                  :precision="2"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="排序权重">
                <el-input-number v-model="templateFormData.sort_order" :min="0" :max="999" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="是否启用">
                <el-switch v-model="templateFormData.is_active" active-text="启用" inactive-text="停用" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="规格描述">
            <el-input v-model="templateFormData.description" placeholder="说明该规格的含义或标准制作指引" />
          </el-form-item>
        </el-card>

        <!-- 默认配料清单管理 -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span class="section-title">🧪 规格默认配料消耗 (可选)</span>
              <el-button type="primary" size="small" icon="Plus" @click="handleAddTemplateIngredient">
                添加物料配方
              </el-button>
            </div>
          </template>

          <div v-if="templateFormData.ingredients.length === 0" style="text-align: center; color: #909399; padding: 12px 0;">
            暂未添加默认配料（该规格不额外消耗或改变基础原料）
          </div>

          <el-table v-else :data="templateFormData.ingredients" size="small" border style="width: 100%">
            <el-table-column label="物料名称 (Material)" min-width="180">
              <template #default="{ row }">
                <el-select
                  v-model="row.material"
                  placeholder="选择仓库物料"
                  filterable
                  style="width: 100%;"
                  @change="(val: any) => handleTemplateMaterialSelect(row, val)"
                >
                  <el-option
                    v-for="m in materialOptions"
                    :key="m.name"
                    :label="`${m.name} (${m.code}) - ${m.unit}`"
                    :value="m.name"
                  />
                </el-select>
              </template>
            </el-table-column>

            <el-table-column label="默认用量" width="150">
              <template #default="{ row }">
                <el-input-number v-model="row.quantity" :min="0.01" :step="1" :precision="2" style="width: 100%;" />
              </template>
            </el-table-column>

            <el-table-column label="计量单位" width="120">
              <template #default="{ row }">
                <el-input v-model="row.unit" placeholder="留空使用默认" />
              </template>
            </el-table-column>

            <el-table-column label="操作" width="80" align="center">
              <template #default="{ $index }">
                <el-button type="danger" link size="small" @click="templateFormData.ingredients.splice($index, 1)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-form>

      <template #footer>
        <el-button @click="showTemplateDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitTemplateLoading" @click="handleSubmitTemplate">
          确认保存
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 3: 新建/编辑菜单品类分类 (GlobalMenuCategory) -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showCategoryDialog"
      :title="isEditCategory ? `编辑菜单品类 (ID: ${currentCategoryId})` : '新建菜单品类分类'"
      width="540px"
    >
      <el-form :model="categoryFormData" label-width="110px">
        <el-form-item label="设备硬件机型" required>
          <el-select v-model="categoryFormData.device_model" placeholder="请选择绑定的设备型号" style="width: 100%;">
            <el-option
              v-for="m in modelOptions"
              :key="m.id"
              :label="`${m.name} (${m.code})`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="分类名称" required>
          <el-input v-model="categoryFormData.name" placeholder="例如 经典意式 / 特调风味 / 鲜萃冷饮" />
        </el-form-item>

        <el-form-item label="特色标签">
          <el-radio-group v-model="categoryFormData.label">
            <el-radio label="recomm">推荐 (recomm)</el-radio>
            <el-radio label="hot">热销 (hot)</el-radio>
            <el-radio label="new">新品 (new)</el-radio>
            <el-radio label="classic">经典 (classic)</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="排序权重">
          <el-input-number v-model="categoryFormData.sort_order" :min="0" :max="999" placeholder="数值越小越靠前" />
        </el-form-item>

        <el-form-item label="是否启用">
          <el-switch v-model="categoryFormData.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCategoryDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitCategoryLoading" @click="handleSubmitCategory">
          确认保存
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 4: 定制商品专属原料配方 (Recipe Customization Modal) -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showRecipeModal"
      :title="`定制商品原料配方：${activeRecipeItem?.name || ''}`"
      width="750px"
      top="5vh"
    >
      <div v-if="activeRecipeItem">
        <div style="margin-bottom: 14px; font-size: 13px; color: #606266;">
          为商品的每个规格单独定制物料消耗配方（若不单独定制，则默认继承规格模板的标准配料）。
        </div>

        <el-collapse v-model="activeRecipeCollapse">
          <el-collapse-item
            v-for="sku in activeRecipeItem.skus || []"
            :key="sku.id"
            :title="`规格: [${sku.template_category}] ${sku.template_name} (加价: +¥${(sku.price_delta / 100).toFixed(2)})`"
            :name="sku.id"
          >
            <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
              <span style="font-size: 12px; font-weight: 600; color: #303133;">
                专属物料配比清单:
              </span>
              <el-button type="primary" size="small" icon="Plus" @click="handleAddSkuIngredient(sku)">
                添加物料
              </el-button>
            </div>

            <el-table :data="sku.ingredients || []" size="small" border style="width: 100%">
              <el-table-column label="物料名称" min-width="180">
                <template #default="{ row }">
                  <el-select
                    v-model="row.material"
                    placeholder="选择物料"
                    filterable
                    style="width: 100%;"
                    @change="(val: any) => handleRecipeMaterialSelect(row, val)"
                  >
                    <el-option
                      v-for="m in materialOptions"
                      :key="m.name"
                      :label="`${m.name} (${m.code}) - ${m.unit}`"
                      :value="m.name"
                    />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="用量" width="130">
                <template #default="{ row }">
                  <el-input-number v-model="row.quantity" :min="0.01" :step="1" :precision="2" style="width: 100%;" />
                </template>
              </el-table-column>

              <el-table-column label="单位" width="100">
                <template #default="{ row }">
                  <el-input v-model="row.unit" placeholder="单位" />
                </template>
              </el-table-column>

              <el-table-column label="操作" width="70" align="center">
                <template #default="{ $index }">
                  <el-button type="danger" link size="small" @click="sku.ingredients && sku.ingredients.splice($index, 1)">
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <div style="margin-top: 8px; text-align: right;">
              <el-button
                type="primary"
                size="small"
                :loading="savingSkuId === sku.id"
                @click="handleSaveSkuRecipe(sku)"
              >
                保存此规格配方
              </el-button>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
      <template #footer>
        <el-button @click="showRecipeModal = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 5: 调整商品规格专属配料配方 (GlobalMenuSku Recipe Dialog) -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showSkuRecipeDialog"
      :title="`调整规格配料配方：[${currentEditingSku?.item_name || ''}] - ${currentEditingSku?.template_name || ''} (ID: #${currentEditingSku?.id})`"
      width="680px"
    >
      <div style="margin-bottom: 12px; font-size: 13px; color: #606266;">
        💡 提示：为该商品的此规格配置专用的物料消耗配方。保存后此规格将独立生效专属配方（不再受抽象模板变动影响）。
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span style="font-weight: 600; font-size: 13px;">物料消耗清单:</span>
        <el-button type="primary" size="small" icon="Plus" @click="handleAddDialogSkuIngredient">
          + 添加物料
        </el-button>
      </div>

      <div v-if="skuRecipeIngredients.length === 0" style="text-align: center; color: #909399; padding: 12px 0;">
        暂无配料消耗（点击右上角“+ 添加物料”配置配方）
      </div>

      <el-table v-else :data="skuRecipeIngredients" size="small" border style="width: 100%;">
        <el-table-column label="物料名称" min-width="180">
          <template #default="{ row }">
            <el-select
              v-model="row.material"
              placeholder="选择仓库物料"
              filterable
              size="small"
              style="width: 100%;"
              @change="(val: any) => handleRecipeMaterialSelect(row, val)"
            >
              <el-option
                v-for="m in materialOptions"
                :key="m.name"
                :label="`${m.name} (${m.code}) - ${m.unit}`"
                :value="m.name"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="用量" width="130">
          <template #default="{ row }">
            <el-input-number v-model="row.quantity" :min="0.01" :step="1" :precision="2" size="small" style="width: 100%;" />
          </template>
        </el-table-column>
        <el-table-column label="单位" width="100">
          <template #default="{ row }">
            <el-input v-model="row.unit" size="small" placeholder="单位" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70" align="center">
          <template #default="{ $index }">
            <el-button type="danger" link size="small" @click="skuRecipeIngredients.splice($index, 1)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="showSkuRecipeDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingSkuRecipe" @click="handleSaveSkuRecipeDialog">
          确认保存配方
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 6: 调整规格加价与设置 (GlobalMenuSku Price & Status Dialog) -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showSkuPriceDialog"
      :title="`调整规格加价与设置：[${currentEditingSku?.item_name || ''}] - ${currentEditingSku?.template_name || ''}`"
      width="480px"
    >
      <el-form label-width="110px">
        <el-form-item label="所属商品">
          <el-input :value="currentEditingSku?.item_name" disabled />
        </el-form-item>
        <el-form-item label="规格名称">
          <el-input :value="`[${currentEditingSku?.template_category}] ${currentEditingSku?.template_name}`" disabled />
        </el-form-item>
        <el-form-item label="商品基准价">
          <el-input :value="formatCurrency(currentEditingSku?.item_base_price)" disabled />
        </el-form-item>
        <el-form-item label="规格加价 (元)" required>
          <el-input-number
            v-model="skuPriceForm.priceDeltaYuan"
            :min="-999"
            :step="0.5"
            :precision="2"
            style="width: 100%;"
          />
        </el-form-item>
        <el-form-item label="叠加后总价">
          <span style="font-weight: bold; color: #E6A23C; font-size: 15px;">
            {{ formatCurrency(yuanToFen((fenToYuan(currentEditingSku?.item_base_price) || 0) + skuPriceForm.priceDeltaYuan)) }}
          </span>
        </el-form-item>
        <el-form-item label="排序权重">
          <el-input-number v-model="skuPriceForm.sort_order" :min="0" :max="999" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="skuPriceForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSkuPriceDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingSkuPrice" @click="handleSaveSkuPriceDialog">
          确认更新
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import {
  getGlobalItemsApi,
  createGlobalItemApi,
  updateGlobalItemApi,
  deleteGlobalItemApi,
  getSkuTemplatesApi,
  createSkuTemplateApi,
  updateSkuTemplateApi,
  deleteSkuTemplateApi,
  getGlobalCategoriesApi,
  createGlobalCategoryApi,
  updateGlobalCategoryApi,
  deleteGlobalCategoryApi,
  getAllGlobalSkusApi,
  updateItemSkuApi,
  resetItemSkuRecipeApi,
  deleteItemSkuApi,
} from '@/api/menus'
import { getMaterialsApi } from '@/api/inventory'
import { getDeviceModelsApi } from '@/api/global_config'
import { uploadFileApi } from '@/api/common'
import { fenToYuan, yuanToFen, formatCurrency, formatFenToYuan, formatYuan } from '@/utils/money'
import type {
  GlobalMenuItem,
  GlobalMenuSku,
  SkuTemplateItem,
  MaterialItem,
  CategoryItem,
  DeviceModelItem,
} from '@/types'

const route = useRoute()
const router = useRouter()

// 选项卡状态 (items | skus | templates | categories)
const activeTab = ref<string>('items')

// 数据列表
const itemList = ref<GlobalMenuItem[]>([])
const skuList = ref<GlobalMenuSku[]>([])
const templateList = ref<SkuTemplateItem[]>([])
const categoryList = ref<CategoryItem[]>([])
const modelOptions = ref<DeviceModelItem[]>([])
const materialOptions = ref<MaterialItem[]>([])

// Loading 状态
const loadingItems = ref(false)
const loadingSkus = ref(false)
const loadingTemplates = ref(false)
const loadingCategories = ref(false)

// 筛选字段
const selectedCategory = ref<number | ''>('')
const itemSearchKeyword = ref('')
const filterSkuItem = ref<number | ''>('')
const filterSkuCategory = ref<number | ''>('')
const filterSkuTemplateCat = ref<string>('')
const skuSearchKeyword = ref<string>('')
const filterTemplateCategory = ref('')
const templateSearchKeyword = ref('')
const selectedCategoryModel = ref<number | ''>('')

// -------------------------------------------------------------
// 0. 菜单规格库 (GlobalMenuSku) 相关状态与逻辑
// -------------------------------------------------------------
const showSkuRecipeDialog = ref(false)
const currentEditingSku = ref<GlobalMenuSku | null>(null)
const skuRecipeIngredients = ref<Array<{ material: string; quantity: number; unit: string }>>([])
const savingSkuRecipe = ref(false)

const showSkuPriceDialog = ref(false)
const skuPriceForm = reactive({
  id: 0,
  priceDeltaYuan: 0,
  sort_order: 0,
  is_active: true,
})
const savingSkuPrice = ref(false)

// -------------------------------------------------------------
// 1. 商品相关状态与逻辑
// -------------------------------------------------------------
const showItemDialog = ref(false)
const isEditItem = ref(false)
const submitItemLoading = ref(false)
const currentItemId = ref<number | null>(null)

const itemFormData = reactive<any>({
  name: '',
  category: undefined,
  priceYuan: 18.00,
  main_ingredients: '',
  price_description: '',
  image_url: '',
  detail_page: '',
  description: '',
  sort_order: 0,
  is_active: true,
  skus: [] as Array<{
    id?: number
    template: number | undefined
    template_name?: string
    template_category?: string
    default_price_delta?: number
    priceDeltaYuan: number
    is_active: boolean
    sort_order: number
    ingredients?: Array<{ material: string; quantity: number; unit: string }>
  }>,
})

// 定制配方弹窗
const showRecipeModal = ref(false)
const activeRecipeItem = ref<GlobalMenuItem | null>(null)
const activeRecipeCollapse = ref<any[]>([])
const savingSkuId = ref<number | null>(null)

function getCategoryTag(cat: string) {
  const map: Record<string, string> = {
    杯型: 'primary',
    温度: 'danger',
    糖度: 'warning',
    风味: 'success',
    default: 'info',
  }
  return map[cat] || 'info'
}

// -------------------------------------------------------------
// 2. 规格模板相关状态与逻辑
// -------------------------------------------------------------
const showTemplateDialog = ref(false)
const isEditTemplate = ref(false)
const submitTemplateLoading = ref(false)
const currentTemplateId = ref<number | null>(null)

const presetTemplateCategories = ref<string[]>(['杯型', '温度', '糖度', '风味', '加料', '通用'])

const availableTemplateCategories = computed(() => {
  const cats = new Set<string>(presetTemplateCategories.value)
  if (Array.isArray(templateList.value)) {
    templateList.value.forEach((t: any) => {
      if (t.category && String(t.category).trim()) {
        cats.add(String(t.category).trim())
      }
    })
  }
  if (templateFormData.category && String(templateFormData.category).trim()) {
    cats.add(String(templateFormData.category).trim())
  }
  return Array.from(cats)
})

async function handlePromptNewCategory() {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的规格分类名称（例如：奶基底、包装、加料等）：', '新建规格分类', {
      confirmButtonText: '确定添加',
      cancelButtonText: '取消',
      inputPattern: /^.+$/,
      inputErrorMessage: '分类名称不能为空',
      inputPlaceholder: '如：加料、奶基底、浓度'
    })
    const trimmed = String(value || '').trim()
    if (trimmed) {
      if (!presetTemplateCategories.value.includes(trimmed)) {
        presetTemplateCategories.value.push(trimmed)
      }
      templateFormData.category = trimmed
      ElMessage.success(`已设置分类为: ${trimmed}`)
    }
  } catch (e) {
    // canceled
  }
}

function handleCategorySelectBlur(e: any) {
  const inputVal = e?.target?.value?.trim()
  if (inputVal && !templateFormData.category) {
    templateFormData.category = inputVal
    if (!presetTemplateCategories.value.includes(inputVal)) {
      presetTemplateCategories.value.push(inputVal)
    }
  }
}

const templateFormData = reactive<any>({
  category: '杯型',
  name: '',
  priceYuan: 0,
  description: '',
  sort_order: 0,
  is_active: true,
  ingredients: [] as Array<{ material: string; quantity: number; unit: string }>,
})

// -------------------------------------------------------------
// 3. 品类分类相关状态与逻辑
// -------------------------------------------------------------
const showCategoryDialog = ref(false)
const isEditCategory = ref(false)
const submitCategoryLoading = ref(false)
const currentCategoryId = ref<number | null>(null)

const categoryFormData = reactive({
  device_model: undefined as number | undefined,
  name: '',
  label: 'recomm',
  sort_order: 0,
  is_active: true,
})

// =============================================================
// 数据加载函数
// =============================================================
async function fetchItems() {
  loadingItems.value = true
  try {
    const params: any = {}
    if (selectedCategory.value) params.category_id = selectedCategory.value
    if (itemSearchKeyword.value) params.search = itemSearchKeyword.value

    const res = await getGlobalItemsApi(params)
    itemList.value = res.data?.results || []
  } finally {
    loadingItems.value = false
  }
}

async function fetchSkus() {
  loadingSkus.value = true
  try {
    const params: any = { page_size: 200 }
    if (filterSkuItem.value) params.item_id = filterSkuItem.value
    if (filterSkuCategory.value) params.category_id = filterSkuCategory.value
    if (filterSkuTemplateCat.value) params.template_category = filterSkuTemplateCat.value
    if (skuSearchKeyword.value) params.search = skuSearchKeyword.value

    const res = await getAllGlobalSkusApi(params)
    skuList.value = res.data?.results || []
  } finally {
    loadingSkus.value = false
  }
}

async function fetchTemplates() {
  loadingTemplates.value = true
  try {
    const res = await getSkuTemplatesApi({
      category: filterTemplateCategory.value || undefined,
      search: templateSearchKeyword.value || undefined,
    })
    templateList.value = res.data || []
  } finally {
    loadingTemplates.value = false
  }
}

async function fetchCategories() {
  loadingCategories.value = true
  try {
    const res = await getGlobalCategoriesApi({
      device_model: selectedCategoryModel.value || undefined,
    })
    categoryList.value = res.data || []
  } finally {
    loadingCategories.value = false
  }
}

async function fetchCommonMeta() {
  try {
    const [matRes, modRes] = await Promise.all([
      getMaterialsApi({ page_size: 200 }),
      getDeviceModelsApi(),
    ])
    materialOptions.value = matRes.data?.results || []
    modelOptions.value = modRes.data || []
  } catch (e) {
    //
  }
}

async function reloadAll() {
  await Promise.all([fetchItems(), fetchSkus(), fetchTemplates(), fetchCategories(), fetchCommonMeta()])
}

function handleTabChange(tabName: any) {
  router.replace({ query: { ...route.query, tab: tabName } })
  if (tabName === 'skus') {
    fetchSkus()
  } else if (tabName === 'items') {
    fetchItems()
  } else if (tabName === 'templates') {
    fetchTemplates()
  } else if (tabName === 'categories') {
    fetchCategories()
  }
}

// =============================================================
// 菜单规格库 (GlobalMenuSku) 操作
// =============================================================
function handleAddRowIngredient(row: any) {
  if (!row.ingredients) row.ingredients = []
  const firstMat = materialOptions.value[0]
  row.ingredients.push({
    material: firstMat ? firstMat.name : '',
    quantity: 1,
    unit: firstMat ? firstMat.unit : 'g',
  })
}

function handleResetRowIngredientToTemplate(row: any) {
  const target = templateList.value.find((t) => t.id === row.template)
  if (target) {
    row.ingredients = (target.ingredients || []).map((ing: any) => ({
      material: ing.material_name || ing.material,
      quantity: Number(ing.quantity) || 1,
      unit: ing.unit || 'g',
    }))
    ElMessage.info('已恢复该规格模板的默认配料')
  }
}

function openEditSkuRecipeDialog(row: GlobalMenuSku) {
  currentEditingSku.value = row
  const source = (row.ingredients && row.ingredients.length > 0)
    ? row.ingredients
    : (row.effective_ingredients || [])
  skuRecipeIngredients.value = source.map((ing: any) => ({
    material: ing.material_name || ing.material,
    quantity: Number(ing.quantity) || 1,
    unit: ing.unit || '',
  }))
  showSkuRecipeDialog.value = true
}

function handleAddDialogSkuIngredient() {
  const firstMat = materialOptions.value[0]
  skuRecipeIngredients.value.push({
    material: firstMat ? firstMat.name : '',
    quantity: 1,
    unit: firstMat ? firstMat.unit : 'g',
  })
}

async function handleSaveSkuRecipeDialog() {
  if (!currentEditingSku.value) return
  savingSkuRecipe.value = true
  try {
    await updateItemSkuApi(currentEditingSku.value.id, {
      ingredients: skuRecipeIngredients.value.map((ing) => ({
        material: ing.material,
        quantity: ing.quantity,
        unit: ing.unit,
      })) as any,
    })
    ElMessage.success(`规格 [${currentEditingSku.value.item_name} - ${currentEditingSku.value.template_name}] 专属配方已保存`)
    showSkuRecipeDialog.value = false
    fetchSkus()
    fetchItems()
  } finally {
    savingSkuRecipe.value = false
  }
}

async function handleResetSkuRecipe(row: GlobalMenuSku) {
  try {
    await resetItemSkuRecipeApi(row.id)
    ElMessage.success(`规格 [${row.item_name} - ${row.template_name}] 已重置为模板默认配料`)
    fetchSkus()
    fetchItems()
  } catch (e) {
    //
  }
}

function openEditSkuPriceDialog(row: GlobalMenuSku) {
  currentEditingSku.value = row
  skuPriceForm.id = row.id
  skuPriceForm.priceDeltaYuan = fenToYuan(row.price_delta)
  skuPriceForm.sort_order = row.sort_order || 0
  skuPriceForm.is_active = row.is_active
  showSkuPriceDialog.value = true
}

async function handleSaveSkuPriceDialog() {
  savingSkuPrice.value = true
  try {
    await updateItemSkuApi(skuPriceForm.id, {
      price_delta: yuanToFen(skuPriceForm.priceDeltaYuan),
      sort_order: skuPriceForm.sort_order,
      is_active: skuPriceForm.is_active,
    })
    ElMessage.success('规格加价与设置已更新')
    showSkuPriceDialog.value = false
    fetchSkus()
    fetchItems()
  } finally {
    savingSkuPrice.value = false
  }
}

async function handleDeleteSku(skuId: number) {
  try {
    await deleteItemSkuApi(skuId)
    ElMessage.success('商品规格已成功删除')
    fetchSkus()
    fetchItems()
  } catch (e) {
    //
  }
}

async function handleToggleSkuStatus(row: GlobalMenuSku) {
  try {
    await updateItemSkuApi(row.id, { is_active: row.is_active })
    ElMessage.success(`规格 [${row.template_name}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

// =============================================================
// 商品管理操作
// =============================================================
function openCreateItemDialog() {
  isEditItem.value = false
  currentItemId.value = null
  reloadAll()
  Object.assign(itemFormData, {
    name: '',
    category: categoryList.value[0]?.id,
    priceYuan: 18.00,
    main_ingredients: '',
    price_description: '',
    image_url: '',
    detail_page: '',
    description: '',
    sort_order: 0,
    is_active: true,
    skus: [],
  })

  if (templateList.value.length > 0) {
    const defaultTpl = templateList.value[0]
    itemFormData.skus.push({
      template: defaultTpl.id,
      template_name: defaultTpl.name,
      template_category: defaultTpl.category,
      default_price_delta: defaultTpl.default_price_delta,
      priceDeltaYuan: fenToYuan(defaultTpl.default_price_delta),
      is_active: true,
      sort_order: 0,
      ingredients: (defaultTpl.ingredients || []).map((ing: any) => ({
        material: ing.material_name || ing.material,
        quantity: Number(ing.quantity) || 1,
        unit: ing.unit || 'g',
      })),
    })
  }

  showItemDialog.value = true
}

function openEditItemDialog(row: GlobalMenuItem) {
  isEditItem.value = true
  currentItemId.value = row.id
  reloadAll()
  Object.assign(itemFormData, {
    name: row.name,
    category: row.category,
    priceYuan: fenToYuan(row.base_price),
    main_ingredients: row.main_ingredients || '',
    price_description: row.price_description || '',
    image_url: row.image_url || '',
    detail_page: row.detail_page || '',
    description: row.description || '',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
    skus: (row.skus || []).map((sku) => ({
      id: sku.id,
      template: sku.template,
      template_name: sku.template_name,
      template_category: sku.template_category,
      default_price_delta: sku.default_price_delta,
      priceDeltaYuan: fenToYuan(sku.price_delta),
      is_active: sku.is_active,
      sort_order: sku.sort_order || 0,
      ingredients: (sku.ingredients && sku.ingredients.length > 0 ? sku.ingredients : (sku.effective_ingredients || [])).map((ing: any) => ({
        material: ing.material_name || ing.material,
        quantity: Number(ing.quantity) || 1,
        unit: ing.unit || 'g',
      })),
    })),
  })
  showItemDialog.value = true
}

function handleAddSkuRow() {
  const unusedTpl = templateList.value.find(
    (t) => !itemFormData.skus.some((s: any) => s.template === t.id)
  ) || templateList.value[0]

  if (unusedTpl) {
    itemFormData.skus.push({
      template: unusedTpl.id,
      template_name: unusedTpl.name,
      template_category: unusedTpl.category,
      default_price_delta: unusedTpl.default_price_delta,
      priceDeltaYuan: fenToYuan(unusedTpl.default_price_delta),
      is_active: true,
      sort_order: itemFormData.skus.length,
      ingredients: (unusedTpl.ingredients || []).map((ing: any) => ({
        material: ing.material_name || ing.material,
        quantity: Number(ing.quantity) || 1,
        unit: ing.unit || 'g',
      })),
    })
  } else {
    ElMessage.info('已挂载全部规格模板')
  }
}

function handleSkuTemplateSelect(row: any, tplId: number) {
  const target = templateList.value.find((t) => t.id === tplId)
  if (target) {
    row.template_name = target.name
    row.template_category = target.category
    row.default_price_delta = target.default_price_delta
    row.priceDeltaYuan = fenToYuan(target.default_price_delta)
    row.ingredients = (target.ingredients || []).map((ing: any) => ({
      material: ing.material_name || ing.material,
      quantity: Number(ing.quantity) || 1,
      unit: ing.unit || 'g',
    }))
  }
}

function isTemplateAlreadySelected(currentRow: any, tplId: number) {
  return itemFormData.skus.some((s: any) => s !== currentRow && s.template === tplId)
}

function getAccumulatedPrice(index: number): string {
  let total = Number(itemFormData.priceYuan || 0)
  for (let i = 0; i <= index; i++) {
    const sku = itemFormData.skus[i]
    if (sku && sku.is_active !== false) {
      total += Number(sku.priceDeltaYuan || 0)
    }
  }
  return total.toFixed(2)
}

function getTotalCombinedPrice(): string {
  let total = Number(itemFormData.priceYuan || 0)
  for (const sku of itemFormData.skus) {
    if (sku && sku.is_active !== false) {
      total += Number(sku.priceDeltaYuan || 0)
    }
  }
  return total.toFixed(2)
}

function getTotalDeltaPrice(): string {
  let total = 0
  for (const sku of itemFormData.skus) {
    if (sku && sku.is_active !== false) {
      total += Number(sku.priceDeltaYuan || 0)
    }
  }
  return (total >= 0 ? '+' : '') + total.toFixed(2)
}

async function handleUploadImage(uploadFile: any, field: 'image_url' | 'detail_page') {
  const rawFile = uploadFile.raw
  if (!rawFile) return

  // 1. 检查大小
  if (field === 'detail_page') {
    if (rawFile.size > 1 * 1024 * 1024) {
      ElMessage.error('商品详情页图大小不能超过 1MB，请压缩后重试')
      return
    }
  } else if (field === 'image_url') {
    if (rawFile.size > 2 * 1024 * 1024) {
      ElMessage.error('商品主图大小不能超过 2MB，请压缩后重试')
      return
    }
  }

  // 2. 检查图片尺寸
  const objectUrl = URL.createObjectURL(rawFile)
  const img = new Image()
  img.onload = async () => {
    try {
      if (field === 'detail_page') {
        if (img.width !== 750) {
          ElMessage.error(`商品详情页图宽度必须严格为 750px（当前检测为 ${img.width}px），请调整尺寸后再上传`)
          URL.revokeObjectURL(objectUrl)
          return
        }
      } else if (field === 'image_url') {
        const diff = Math.abs(img.width - img.height)
        if (diff > 40) {
          ElMessage.warning(`提示：当前主图尺寸为 ${img.width}x${img.height}，推荐使用 1:1 正方形比例 (如 800x800)`)
        }
      }

      const res = await uploadFileApi(rawFile, 'menus')
      if (res.data && res.data.url) {
        itemFormData[field] = res.data.url
        ElMessage.success(`图片上传成功 (${img.width}x${img.height})`)
      }
    } catch (e) {
      ElMessage.error('图片上传失败，请重试')
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  }
  img.onerror = () => {
    ElMessage.error('无法读取图片文件，请上传有效的 JPG/PNG/WebP 格式图片')
    URL.revokeObjectURL(objectUrl)
  }
  img.src = objectUrl
}

async function handleSubmitItem() {
  if (!itemFormData.name || !itemFormData.category) {
    ElMessage.warning('商品名称和所属分类为必填项')
    return
  }

  submitItemLoading.value = true
  try {
    const payload = {
      name: itemFormData.name,
      category: itemFormData.category,
      base_price: yuanToFen(itemFormData.priceYuan),
      main_ingredients: itemFormData.main_ingredients,
      price_description: itemFormData.price_description,
      image_url: itemFormData.image_url,
      detail_page: itemFormData.detail_page || null,
      description: itemFormData.description,
      sort_order: itemFormData.sort_order,
      is_active: itemFormData.is_active,
      skus: itemFormData.skus
        .filter((s: any) => s.template)
        .map((s: any) => ({
          template_id: s.template,
          price_delta: yuanToFen(s.priceDeltaYuan),
          is_active: s.is_active,
          sort_order: s.sort_order,
          ingredients: (s.ingredients || []).map((ing: any) => ({
            material: ing.material,
            quantity: ing.quantity,
            unit: ing.unit,
          })),
        })),
    }

    if (isEditItem.value && currentItemId.value) {
      await updateGlobalItemApi(currentItemId.value, payload)
      ElMessage.success('商品档案及规格已同步保存')
    } else {
      await createGlobalItemApi(payload)
      ElMessage.success('商品档案及规格已创建')
    }
    showItemDialog.value = false
    fetchItems()
    fetchSkus()
  } finally {
    submitItemLoading.value = false
  }
}

async function handleToggleItemStatus(row: GlobalMenuItem) {
  try {
    await updateGlobalItemApi(row.id, { is_active: row.is_active })
    ElMessage.success(`商品 [${row.name}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDeleteItem(id: number) {
  try {
    await deleteGlobalItemApi(id)
    ElMessage.success('全局商品已删除')
    fetchItems()
  } catch (e) {
    //
  }
}

function openRecipeModal(row: GlobalMenuItem) {
  activeRecipeItem.value = JSON.parse(JSON.stringify(row))
  activeRecipeCollapse.value = (row.skus || []).map((s) => s.id)
  showRecipeModal.value = true
}

function handleAddSkuIngredient(sku: GlobalMenuSku) {
  if (!sku.ingredients) sku.ingredients = []
  const firstMat = materialOptions.value[0]
  sku.ingredients.push({
    material: firstMat ? firstMat.name : '',
    quantity: 1,
    unit: firstMat ? firstMat.unit : 'g',
  })
}

function handleRecipeMaterialSelect(row: any, matName: string) {
  const target = materialOptions.value.find((m) => m.name === matName)
  if (target) {
    row.unit = target.unit
  }
}

async function handleSaveSkuRecipe(sku: GlobalMenuSku) {
  savingSkuId.value = sku.id
  try {
    await updateItemSkuApi(sku.id, {
      ingredients: (sku.ingredients || []).map((ing) => ({
        material: ing.material,
        quantity: ing.quantity,
        unit: ing.unit,
      })) as any,
    })
    ElMessage.success(`规格 [${sku.template_name}] 配方已更新`)
    fetchItems()
  } finally {
    savingSkuId.value = null
  }
}

// =============================================================
// 规格模板操作
// =============================================================
function openCreateTemplateDialog() {
  isEditTemplate.value = false
  currentTemplateId.value = null
  Object.assign(templateFormData, {
    category: '杯型',
    name: '',
    priceYuan: 0,
    description: '',
    sort_order: 0,
    is_active: true,
    ingredients: [],
  })
  showTemplateDialog.value = true
}

function openEditTemplateDialog(row: SkuTemplateItem) {
  isEditTemplate.value = true
  currentTemplateId.value = row.id
  Object.assign(templateFormData, {
    category: row.category,
    name: row.name,
    priceYuan: fenToYuan(row.default_price_delta),
    description: row.description || '',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
    ingredients: (row.ingredients || []).map((ing: any) => ({
      material: ing.material_name || ing.material,
      quantity: Number(ing.quantity) || 1,
      unit: ing.unit || '',
    })),
  })
  showTemplateDialog.value = true
}

function handleAddTemplateIngredient() {
  const firstMat = materialOptions.value[0]
  templateFormData.ingredients.push({
    material: firstMat ? firstMat.name : '',
    quantity: 1,
    unit: firstMat ? firstMat.unit : 'g',
  })
}

function handleTemplateMaterialSelect(row: any, matName: string) {
  const target = materialOptions.value.find((m) => m.name === matName)
  if (target) {
    row.unit = target.unit
  }
}

async function handleSubmitTemplate() {
  if (!templateFormData.category || !templateFormData.name) {
    ElMessage.warning('规格分类和规格名称为必填项')
    return
  }

  submitTemplateLoading.value = true
  try {
    const payload = {
      category: templateFormData.category,
      name: templateFormData.name,
      default_price_delta: yuanToFen(templateFormData.priceYuan),
      description: templateFormData.description,
      sort_order: templateFormData.sort_order,
      is_active: templateFormData.is_active,
      ingredients: templateFormData.ingredients.map((ing: any) => ({
        material: ing.material,
        quantity: ing.quantity,
        unit: ing.unit,
      })),
    }

    if (isEditTemplate.value && currentTemplateId.value) {
      await updateSkuTemplateApi(currentTemplateId.value, payload)
      ElMessage.success('规格模板更新成功')
    } else {
      const res = await createSkuTemplateApi(payload)
      ElMessage.success('规格模板创建成功')
      if (showItemDialog.value && res.data) {
        const newTpl = res.data
        itemFormData.skus.push({
          template: newTpl.id,
          template_name: newTpl.name,
          template_category: newTpl.category,
          default_price_delta: newTpl.default_price_delta,
          priceDeltaYuan: fenToYuan(newTpl.default_price_delta),
          is_active: true,
          sort_order: itemFormData.skus.length + 1,
          ingredients: (newTpl.ingredients || []).map((ing: any) => ({
            material: ing.material_name || ing.material,
            quantity: Number(ing.quantity) || 1,
            unit: ing.unit || '',
          })),
        })
        ElMessage.info(`已自动将新规格 [${newTpl.name}] 添加至当前商品`)
      }
    }
    showTemplateDialog.value = false
    await fetchTemplates()
  } finally {
    submitTemplateLoading.value = false
  }
}

async function handleToggleTemplateStatus(row: SkuTemplateItem) {
  try {
    await updateSkuTemplateApi(row.id, { is_active: row.is_active })
    ElMessage.success(`规格 [${row.name}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDeleteTemplate(id: number) {
  try {
    await deleteSkuTemplateApi(id)
    ElMessage.success('规格模板已删除')
    fetchTemplates()
  } catch (e) {
    //
  }
}

// =============================================================
// 品类分类操作
// =============================================================
function openCreateCategoryDialog() {
  isEditCategory.value = false
  currentCategoryId.value = null
  Object.assign(categoryFormData, {
    device_model: modelOptions.value[0]?.id,
    name: '',
    label: 'recomm',
    sort_order: 0,
    is_active: true,
  })
  showCategoryDialog.value = true
}

function openEditCategoryDialog(row: CategoryItem) {
  isEditCategory.value = true
  currentCategoryId.value = row.id
  Object.assign(categoryFormData, {
    device_model: row.device_model,
    name: row.name,
    label: row.label || 'recomm',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
  })
  showCategoryDialog.value = true
}

async function handleSubmitCategory() {
  if (!categoryFormData.name || !categoryFormData.device_model) {
    ElMessage.warning('设备机型和分类名称为必填项')
    return
  }

  submitCategoryLoading.value = true
  try {
    if (isEditCategory.value && currentCategoryId.value) {
      await updateGlobalCategoryApi(currentCategoryId.value, categoryFormData)
      ElMessage.success('品类分类更新成功')
    } else {
      await createGlobalCategoryApi(categoryFormData)
      ElMessage.success('品类分类创建成功')
    }
    showCategoryDialog.value = false
    fetchCategories()
  } finally {
    submitCategoryLoading.value = false
  }
}

async function handleToggleCategoryStatus(row: CategoryItem) {
  try {
    await updateGlobalCategoryApi(row.id, { is_active: row.is_active })
    ElMessage.success(`品类 [${row.name}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDeleteCategory(id: number) {
  try {
    await deleteGlobalCategoryApi(id)
    ElMessage.success('品类分类已删除')
    fetchCategories()
  } catch (e) {
    //
  }
}

// 监听路由参数 ?tab=xxx
watch(
  () => route.query.tab,
  (tab) => {
    if (tab && ['items', 'templates', 'categories'].includes(tab as string)) {
      activeTab.value = tab as string
    }
  },
  { immediate: true }
)

onMounted(() => {
  reloadAll()
})
</script>

<style scoped>
.menu-tabs :deep(.el-tabs__header) {
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

.form-section-card {
  border-radius: 8px;
  background-color: #fafafa;
}
.section-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.image-upload-box {
  background: #ffffff;
  padding: 14px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.box-title {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
}
.box-sub {
  font-size: 11px;
  color: #909399;
  margin-bottom: 8px;
}
.img-preview {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  background: #f8fafc;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
  margin-bottom: 10px;
}
.square-box {
  width: 140px;
  height: 140px;
}
.detail-box {
  width: 140px;
  height: 180px;
}
.preview-inner {
  width: 100%;
  height: 100%;
}
.empty-txt {
  color: #c0c4cc;
  font-size: 12px;
}
.btn-group {
  display: flex;
  gap: 8px;
  align-items: center;
}
.sku-summary-bar {
  margin-top: 12px;
  padding: 10px 16px;
  background: #fdf6ec;
  border-radius: 6px;
  border: 1px solid #faecd8;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 24px;
  font-size: 13px;
  color: #606266;
}
.summary-item strong {
  font-size: 14px;
}
.summary-item.total {
  color: #303133;
}
.summary-item.total strong {
  color: #E6A23C;
  font-size: 16px;
}
</style>
