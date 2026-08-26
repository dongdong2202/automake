import http from './index'
import type {
  ApiResponse,
  PaginatedData,
  CategoryItem,
  SkuTemplateItem,
  GlobalMenuItem,
  GlobalMenuSku
} from '@/types'

// ============================================================
// 规格模板库 (GlobalSkuTemplate)
// ============================================================
export function getSkuTemplatesApi(params?: { category?: string; search?: string }): Promise<ApiResponse<SkuTemplateItem[]>> {
  return http.get('/admin/menus/sku-templates/', { params })
}

export function createSkuTemplateApi(data: Partial<SkuTemplateItem>): Promise<ApiResponse<SkuTemplateItem>> {
  return http.post('/admin/menus/sku-templates/', data)
}

export function updateSkuTemplateApi(id: number | string, data: Partial<SkuTemplateItem>): Promise<ApiResponse<SkuTemplateItem>> {
  return http.put(`/admin/menus/sku-templates/${id}/`, data)
}

export function deleteSkuTemplateApi(id: number | string): Promise<ApiResponse<null>> {
  return http.delete(`/admin/menus/sku-templates/${id}/`)
}

// ============================================================
// 菜单分类 (GlobalMenuCategory)
// ============================================================
export function getGlobalCategoriesApi(params?: { device_model?: number | string }): Promise<ApiResponse<CategoryItem[]>> {
  return http.get('/admin/menus/global-categories/', { params })
}

export function createGlobalCategoryApi(data: Partial<CategoryItem>): Promise<ApiResponse<CategoryItem>> {
  return http.post('/admin/menus/global-categories/', data)
}

export function updateGlobalCategoryApi(id: number | string, data: Partial<CategoryItem>): Promise<ApiResponse<CategoryItem>> {
  return http.put(`/admin/menus/global-categories/${id}/`, data)
}

export function deleteGlobalCategoryApi(id: number | string): Promise<ApiResponse<null>> {
  return http.delete(`/admin/menus/global-categories/${id}/`)
}

// ============================================================
// 全局商品 (GlobalMenuItem)
// ============================================================
export function getGlobalItemsApi(params?: { category_id?: number | string; search?: string; page?: number; page_size?: number }): Promise<ApiResponse<PaginatedData<GlobalMenuItem>>> {
  return http.get('/admin/menus/global-items/', { params })
}

export function getGlobalItemDetailApi(id: number | string): Promise<ApiResponse<GlobalMenuItem>> {
  return http.get(`/admin/menus/global-items/${id}/`)
}

export function createGlobalItemApi(data: any): Promise<ApiResponse<GlobalMenuItem>> {
  return http.post('/admin/menus/global-items/', data)
}

export function updateGlobalItemApi(id: number | string, data: any): Promise<ApiResponse<GlobalMenuItem>> {
  return http.put(`/admin/menus/global-items/${id}/`, data)
}

export function deleteGlobalItemApi(id: number | string): Promise<ApiResponse<null>> {
  return http.delete(`/admin/menus/global-items/${id}/`)
}

// ============================================================
// 商品规格与配方 (GlobalMenuSku)
// ============================================================
export function getAllGlobalSkusApi(params?: {
  item_id?: number | string
  category_id?: number | string
  template_category?: string
  search?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<PaginatedData<GlobalMenuSku>>> {
  return http.get('/admin/menus/global-skus/', { params })
}

export function getItemSkusApi(itemId: number | string): Promise<ApiResponse<GlobalMenuSku[]>> {
  return http.get(`/admin/menus/global-items/${itemId}/skus/`)
}

export function bindItemSkuApi(itemId: number | string, data: { template_id: number; price_delta?: number; is_active?: boolean; sort_order?: number; ingredients?: any[] }): Promise<ApiResponse<GlobalMenuSku>> {
  return http.post(`/admin/menus/global-items/${itemId}/skus/`, data)
}

export function updateItemSkuApi(skuId: number | string, data: Partial<GlobalMenuSku>): Promise<ApiResponse<GlobalMenuSku>> {
  return http.put(`/admin/menus/global-skus/${skuId}/`, data)
}

export function resetItemSkuRecipeApi(skuId: number | string): Promise<ApiResponse<GlobalMenuSku>> {
  return http.post(`/admin/menus/global-skus/${skuId}/reset-recipe/`)
}

export function deleteItemSkuApi(skuId: number | string): Promise<ApiResponse<null>> {
  return http.delete(`/admin/menus/global-skus/${skuId}/`)
}

// ============================================================
// 门店/设备菜单同步与规格微调 (StoreMenuItem & StoreMenuSku)
// ============================================================
export function getStoreMenuItemsApi(params?: any): Promise<ApiResponse<PaginatedData<any>>> {
  return http.get('/admin/menus/store-items/', { params })
}

export function updateStoreMenuItemApi(id: number | string, data: any): Promise<ApiResponse<any>> {
  return http.put(`/admin/menus/store-items/${id}/`, data)
}

export function getStoreItemSkusApi(itemId: number | string): Promise<ApiResponse<any[]>> {
  return http.get(`/admin/menus/store-items/${itemId}/skus/`)
}

export function updateStoreMenuSkuApi(skuId: number | string, data: any): Promise<ApiResponse<any>> {
  return http.put(`/admin/menus/store-skus/${skuId}/`, data)
}

export function syncStoreMenuApi(storeId: number | string): Promise<ApiResponse<any>> {
  return http.post(`/admin/menus/store-sync/${storeId}/`)
}
