export interface UserInfo {
  id: number
  username: string
  role: 'super_admin' | 'admin' | 'material_admin' | 'customer'
  is_super_admin: boolean
  is_material_admin: boolean
  stores: Array<{ id: number; name: string; code: string }>
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

export interface PaginatedData<T> {
  count: number
  page: number
  page_size: number
  total_pages: number
  results: T[]
}

export interface StoreItem {
  id: number
  name: string
  description?: string
  address?: string
  lat?: number | string | null
  lng?: number | string | null
  contact_phone?: string
  code?: string
  status: 'open' | 'closed' | 'paused'
  business_hours: Record<string, string>
  cover_image?: string
  sort_order?: number
  device_count?: number
  created_at: string
}

export interface DeviceItem {
  id: number
  device_sn: string
  device_name: string
  key_code?: string
  store?: number
  store_name?: string
  device_model?: number
  device_model_name?: string
  status: 'online' | 'offline' | 'fault'
  firmware_version?: string
  resource_version?: string
  mqtt_topic_prefix?: string
  gps_coordinate?: string
  last_heartbeat_at?: string
  province?: string
  city?: string
  address?: string
  lat?: number | string | null
  lng?: number | string | null
  extra_config?: Record<string, any>
  barrels?: BarrelDictItem[]
  monitor_snapshot?: any
}

export interface BarrelDictItem {
  id: number
  barrel_code: string
  material: number
  material_name: string
  material_type: string
  device: number
  device_sn?: string
  device_name?: string
  store_name?: string
  created_by_username?: string
  created_at: string
}

export interface DeviceModelItem {
  id: number
  name: string
  code: string
  description?: string
  device_count?: number
  created_at: string
}

export interface CategoryItem {
  id: number
  device_model: number
  device_model_name?: string
  name: string
  label?: string
  icon_url?: string
  sort_order: number
  is_active: boolean
  item_count?: number
  created_at?: string
}

export interface SkuTemplateIngredient {
  id?: number
  material: string
  material_name?: string
  material_code?: string
  quantity: number
  unit?: string
}

export interface SkuTemplateItem {
  id: number
  category: string
  name: string
  default_price_delta: number
  description?: string
  is_active: boolean
  sort_order: number
  ingredients?: SkuTemplateIngredient[]
  sku_count?: number
  created_at?: string
  updated_at?: string
}

export interface GlobalSkuIngredient {
  id?: number
  material: string
  material_name?: string
  material_code?: string
  quantity: number
  unit?: string
}

export interface GlobalMenuSku {
  id: number
  item: number
  item_name?: string
  item_category_name?: string
  item_base_price?: number
  template: number
  template_name: string
  template_category: string
  default_price_delta: number
  price_delta: number
  final_price?: number
  is_custom_recipe?: boolean
  is_active: boolean
  sort_order: number
  ingredients?: GlobalSkuIngredient[]
  effective_ingredients?: Array<{
    material: string
    material_code: string
    quantity: number
    unit: string
    is_custom: boolean
  }>
  created_at?: string
  updated_at?: string
}

export interface GlobalMenuItem {
  id: number
  category: number
  category_name?: string
  device_model_name?: string
  name: string
  description?: string
  image_url?: string
  base_price: number
  main_ingredients?: string
  price_description?: string
  detail_page?: string
  sort_order: number
  is_active: boolean
  skus?: GlobalMenuSku[]
  created_at?: string
  updated_at?: string
}

export interface StoreMenuSku {
  id: number
  item: number
  global_sku: number
  global_sku_id: number
  template_id: number
  template_name: string
  template_category: string
  global_sku_is_active: boolean
  global_price_delta: number
  global_final_price: number
  price_delta: number
  final_price: number
  is_custom_recipe: boolean
  effective_ingredients?: Array<{
    material: string
    material_code: string
    quantity: number
    unit: string
    is_custom: boolean
  }>
  is_active: boolean
  sort_order: number
}

export interface StoreMenuItem {
  id: number
  store: number
  store_name?: string
  device_model?: number
  global_item: number
  global_item_name: string
  category_name?: string
  global_base_price: number
  base_price: number
  is_active: boolean
  sort_order: number
  skus?: StoreMenuSku[]
  editPriceYuan?: number
  statusLoading?: boolean
  created_at?: string
  updated_at?: string
}

export interface PosterItem {
  id: number
  title: string
  horizontal_image?: string
  vertical_image?: string
  banner_image?: string
  stores: number[]
  devices: number[]
  stores_info?: Array<{ id: number; name: string }>
  devices_info?: Array<{ id: number; device_sn: string; device_name: string }>
  version: number
  remarks?: string
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface MaterialItem {
  id: number
  name: string
  code: string
  material_type: string
  price: string | number
  quantity: string | number
  unit: string
  shelf_life?: string
  storage_conditions?: string
  retrieve_count: number
  created_at: string
}

export interface InventoryRecordItem {
  id: number
  material: number
  material_name: string
  material_code: string
  material_unit: string
  record_type: 'in' | 'out'
  quantity: string | number
  price?: string | number
  store?: number
  store_name?: string
  operator?: number
  operator_username?: string
  expiration_date?: string
  remarks?: string
  created_at: string
}

export interface OrderItemRecord {
  id: number
  order_no: string
  store?: number
  store_name?: string
  device?: number
  device_sn?: string
  status: string
  status_display: string
  total_amount: number
  pay_amount: number
  remark?: string
  paid_at?: string
  done_at?: string
  created_at: string
  items?: Array<{
    id: number
    item_name: string
    sku_name: string
    unit_price: number
    quantity: number
    subtotal: number
  }>
  pickup_code?: string
}

export interface NotifyEventItem {
  id: number
  level: 'info' | 'warning' | 'critical'
  level_display: string
  event_type: string
  event_type_display: string
  title: string
  content: string
  device_sn?: string
  order_no?: string
  is_handled: boolean
  handled_at?: string
  handled_by_username?: string
  created_at: string
}
