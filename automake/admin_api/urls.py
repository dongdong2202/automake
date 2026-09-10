from django.urls import path
from .views import dashboard, analytics, stores, devices, menus, inventory, orders, notifications, users, global_config, upload

urlpatterns = [
    # 通用文件上传
    path('upload/', upload.FileUploadView.as_view(), name='admin-file-upload'),

    # 运营驾驶舱 Dashboard
    path('dashboard/stats', dashboard.DashboardStatsView.as_view(), name='admin-dashboard-stats'),

    # 数据分析 (Analytics) - 6 大分析模块
    # 1. 销售分析
    path('analytics/sales/trend', analytics.SalesTrendAnalyticsView.as_view(), name='analytics-sales-trend'),
    path('analytics/sales/by-hour', analytics.SalesByHourAnalyticsView.as_view(), name='analytics-sales-hour'),
    path('analytics/sales/by-weekday', analytics.SalesByWeekdayAnalyticsView.as_view(), name='analytics-sales-weekday'),
    path('analytics/sales/by-store', analytics.SalesByStoreAnalyticsView.as_view(), name='analytics-sales-store'),
    path('analytics/sales/by-device', analytics.SalesByDeviceAnalyticsView.as_view(), name='analytics-sales-device'),
    path('analytics/sales/funnel', analytics.SalesFunnelAnalyticsView.as_view(), name='analytics-sales-funnel'),

    # 2. 财务概览
    path('analytics/finance/summary', analytics.FinanceSummaryAnalyticsView.as_view(), name='analytics-finance-summary'),
    path('analytics/finance/trend', analytics.FinanceTrendAnalyticsView.as_view(), name='analytics-finance-trend'),
    path('analytics/finance/category-share', analytics.FinanceCategoryShareAnalyticsView.as_view(), name='analytics-finance-category'),

    # 3. 产品分析
    path('analytics/products/ranking', analytics.ProductRankingAnalyticsView.as_view(), name='analytics-product-ranking'),
    path('analytics/products/sku-preferences', analytics.ProductSkuPreferencesAnalyticsView.as_view(), name='analytics-product-sku'),

    # 4. 设备运维分析
    path('analytics/devices/uptime', analytics.DeviceUptimeAnalyticsView.as_view(), name='analytics-device-uptime'),
    path('analytics/devices/alarm-trend', analytics.DeviceAlarmTrendAnalyticsView.as_view(), name='analytics-device-alarm-trend'),

    # 5. 物料进销存分析
    path('analytics/materials/stock-status', analytics.MaterialStockStatusAnalyticsView.as_view(), name='analytics-material-stock'),
    path('analytics/materials/consumption', analytics.MaterialConsumptionTrendAnalyticsView.as_view(), name='analytics-material-consumption'),
    path('analytics/materials/replenishment-forecast', analytics.MaterialForecastAnalyticsView.as_view(), name='analytics-material-forecast'),

    # 6. 客户分析
    path('analytics/customers/growth', analytics.CustomerGrowthAnalyticsView.as_view(), name='analytics-customer-growth'),
    path('analytics/customers/order-frequency', analytics.CustomerFrequencyAnalyticsView.as_view(), name='analytics-customer-frequency'),

    # 门店管理 CRUD & 门店自身库存 & 出库加料到设备 & 调拨流水
    path('stores/', stores.StoreListCreateView.as_view(), name='admin-store-list-create'),
    path('stores/inventory/', stores.StoreInventoryListView.as_view(), name='admin-store-inventory-all'),
    path('stores/records/', stores.StoreInventoryRecordListView.as_view(), name='admin-store-records-all'),
    path('stores/batches/', stores.StoreBatchListView.as_view(), name='admin-store-batches-all'),
    path('stores/<int:pk>/', stores.StoreDetailView.as_view(), name='admin-store-detail'),
    path('stores/<int:store_id>/inventory/', stores.StoreInventoryListView.as_view(), name='admin-store-inventory-list'),
    path('stores/<int:store_id>/dispatch-to-device/', stores.StoreDispatchToDeviceView.as_view(), name='admin-store-dispatch-to-device'),
    path('stores/<int:store_id>/records/', stores.StoreInventoryRecordListView.as_view(), name='admin-store-records-list'),
    path('stores/<int:store_id>/batches/', stores.StoreBatchListView.as_view(), name='admin-store-batches-list'),

    # 设备管理 CRUD & 料桶配置 & 海报 & 设备库存流水
    path('devices/', devices.DeviceListCreateView.as_view(), name='admin-device-list-create'),
    path('devices/records/', devices.DeviceInventoryRecordListView.as_view(), name='admin-device-records-all'),
    path('devices/stocks-overview/', devices.DeviceStockOverviewView.as_view(), name='admin-device-stocks-overview'),
    path('devices/<str:sn>/records/', devices.DeviceInventoryRecordListView.as_view(), name='admin-device-records-list'),
    path('devices/<str:sn>/', devices.DeviceDetailView.as_view(), name='admin-device-detail'),
    path('devices/<str:sn>/barrels/', devices.DeviceBarrelDictListView.as_view(), name='admin-device-barrels'),
    path('devices/barrel-dicts/', devices.GlobalBarrelDictListView.as_view(), name='admin-global-barrel-dicts'),
    path('devices/barrel-dicts/<int:pk>/', devices.GlobalBarrelDictDetailView.as_view(), name='admin-global-barrel-dict-detail'),
    path('posters/', devices.DevicePosterListView.as_view(), name='admin-poster-list-create'),
    path('posters/<int:pk>/', devices.DevicePosterDetailView.as_view(), name='admin-poster-detail'),

    # 菜单与规格配方管理
    path('menus/sku-templates/', menus.GlobalSkuTemplateListView.as_view(), name='admin-menu-sku-templates'),
    path('menus/sku-templates/<int:pk>/', menus.GlobalSkuTemplateDetailView.as_view(), name='admin-menu-sku-template-detail'),
    path('menus/global-categories/', menus.GlobalMenuCategoryListView.as_view(), name='admin-menu-categories'),
    path('menus/global-categories/<int:pk>/', menus.GlobalMenuCategoryDetailView.as_view(), name='admin-menu-category-detail'),
    path('menus/global-items/', menus.GlobalMenuItemListView.as_view(), name='admin-menu-global-items'),
    path('menus/global-items/<int:pk>/', menus.GlobalMenuItemDetailView.as_view(), name='admin-menu-global-item-detail'),
    path('menus/global-items/<int:item_id>/skus/', menus.GlobalMenuItemSkuListView.as_view(), name='admin-menu-global-item-skus'),
    path('menus/global-skus/', menus.GlobalMenuSkuListView.as_view(), name='admin-menu-global-skus'),
    path('menus/global-skus/<int:pk>/', menus.GlobalMenuSkuDetailView.as_view(), name='admin-menu-global-sku-detail'),
    path('menus/global-skus/<int:pk>/reset-recipe/', menus.GlobalMenuSkuResetRecipeView.as_view(), name='admin-menu-global-sku-reset-recipe'),
    path('menus/store-items/', menus.StoreMenuItemListView.as_view(), name='admin-menu-store-items'),
    path('menus/store-items/<int:pk>/', menus.StoreMenuItemDetailView.as_view(), name='admin-menu-store-item-detail'),
    path('menus/store-items/<int:item_id>/skus/', menus.StoreMenuItemSkuListView.as_view(), name='admin-menu-store-item-skus'),
    path('menus/store-skus/<int:pk>/', menus.StoreMenuSkuDetailView.as_view(), name='admin-menu-store-sku-detail'),
    path('menus/store-sync/<int:store_id>/', menus.StoreMenuSyncView.as_view(), name='admin-menu-store-sync'),

    # 物料进销存
    path('inventory/materials/', inventory.MaterialListCreateView.as_view(), name='admin-material-list-create'),
    path('inventory/materials/<int:pk>/', inventory.MaterialDetailView.as_view(), name='admin-material-detail'),
    path('inventory/records/', inventory.InventoryRecordListCreateView.as_view(), name='admin-inventory-records'),
    path('inventory/check-expiration/', inventory.CheckInventoryExpirationView.as_view(), name='admin-inventory-check-expiration'),
    path('inventory/expiration-summary/', inventory.CheckInventoryExpirationView.as_view(), name='admin-inventory-expiration-summary'),

    # 订单与退款
    path('orders/', orders.OrderListView.as_view(), name='admin-order-list'),
    path('orders/<str:order_no>/', orders.OrderDetailView.as_view(), name='admin-order-detail'),
    path('orders/<str:order_no>/refund/', orders.OrderRefundActionView.as_view(), name='admin-order-refund'),

    # 告警与事件通知
    path('notifications/events/', notifications.NotifyEventListView.as_view(), name='admin-notify-events'),
    path('notifications/events/<int:pk>/handle/', notifications.NotifyEventHandleView.as_view(), name='admin-notify-event-handle'),

    # 运营人员与权限
    path('users/', users.UserAdminListView.as_view(), name='admin-user-list-create'),
    path('users/<int:pk>/', users.UserAdminDetailView.as_view(), name='admin-user-detail'),

    # 全局型号配置
    path('global-config/device-models/', global_config.DeviceModelListView.as_view(), name='admin-device-models'),
    path('global-config/device-models/<int:pk>/', global_config.DeviceModelDetailView.as_view(), name='admin-device-model-detail'),
]
