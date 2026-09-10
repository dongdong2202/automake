# 智能上位机终端 (Kiosk) 全流程开发实现手册

> 本文档面向后端与嵌入式开发人员，详细阐述基于触控屏上位机终端（`simulator/kiosk/`）从**下单、支付、出单到退款**的端到端全链路业务流转，逐层剖析每一步的前端函数、网络接口、后端视图与底层服务函数，并深度解析**物料库存校验（Precheck）**与**悲观锁原子锁库（Stock Locking）**的底层实现原理。

---

## 目录
1. [系统总体拓扑与分层架构](#一系统总体拓扑与分层架构)
2. [核心重点一：物料与库存校验实现 (Precheck)](#二核心重点一物料与库存校验实现-precheck)
3. [核心重点二：锁库存与并发防超卖实现 (Stock Locking)](#三核心重点二锁库存与并发防超卖实现-stock-locking)
4. [全流程步骤详解](#四全流程步骤详解)
   - [阶段 1：上位机初始化与测试数据就绪](#阶段-1上位机初始化与测试数据就绪)
   - [阶段 2：点餐选配与下单创建](#阶段-2点餐选配与下单创建)
   - [阶段 3：双模式微信真实支付与状态确认](#阶段-3双模式微信真实支付与状态确认)
   - [阶段 4：出单制作与物理出杯履约](#阶段-4出单制作与物理出杯履约)
   - [阶段 5：未制作退款与物料全数放库](#阶段-5未制作退款与物料全数放库)
5. [全链路函数调用速查总表](#五全链路函数调用速查总表)

---

## 一、系统总体拓扑与分层架构

```
┌────────────────────────────────────────────────────────────────────────┐
│                   触控屏上位机终端 (Kiosk Terminal)                     │
│               simulator/templates/simulator/kiosk.html                 │
└───────────────┬────────────────────────────────────────┬───────────────┘
                │ HTTP REST API                          │ MQTT (QoS 1)
                ▼                                        ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│       Django 后端业务服务集群          │  │       EMQX 物联网代理         │
│   (orders / payments / devices)      │  │ (automake/device/+/status)   │
└───────────────┬──────────────────────┘  └──────────────┬───────────────┘
                │                                        │
        ┌───────┴───────────────┐                        │
        ▼                       ▼                        ▼
┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────────┐
│   MySQL 关系库   │  │   Redis 内存缓存  │  │   硬件主控板 (PLC/单片机)  │
│ 耗材库存、订单主从表 │  │ 物理料桶、在途预扣   │  │ 磨豆机、注水阀、落杯电机    │
└──────────────────┘  └──────────────────┘  └────────────────────────────┘
```

### 1.1 存储分层与介质隔离机制
为应对高并发下高频读写和物理耗材精准盘点的双重诉求，系统采用**分层隔离存储模型**：
1. **杯型与物理耗材（MySQL 强一致持久化）**：
   - 数据表：`devices_deviceconsumablestock`（关联 `inventory_material`）。
   - 托管物料：纸大杯 (`paperL`)、纸中杯 (`paperM`)、塑料大杯 (`plasticL`)、塑料中杯 (`plasticM`)、杯盖 (`lid`)、封口膜 (`membrane`)。
   - 扣减机制：通过数据库事务排他行级悲观锁 `select_for_update()` 保证原子扣减。
2. **食材与物理料桶余量（Redis 物理监控缓存）**：
   - 键名规范：`automake:stock:{device_sn}:{material_code}`（通过 `utils.redis_keys.get_stock_key` 生成）。
   - 托管物料：咖啡豆 (`coffee_bean`, 单位 g)、鲜奶 (`fresh_milk`, 单位 ml)、橙汁 (`orange_juice`, 单位 ml)、水 (`water`, 单位 ml)。
   - 扣减机制：Redis 原子命令 `decrby` 与分布式 Lua 脚本。

---

## 二、核心重点一：物料与库存校验实现 (Precheck)

库存校验贯穿在用户**加购/改数量**（防抖预检）以及**确认下单**的每个瞬间，确保**绝不超卖、绝不出现收了款却因缺杯/缺料无法出餐**的情况。

```
[用户选配加购] 
      │
      ▼
triggerAutoPrecheck() (防抖 250ms)
      │
      ▼
POST /api/order/precheck 
      │
      ├──> calculate_required_materials() ──> [规则纠偏: 热饮禁塑料杯/纸杯必配盖/每杯必有膜]
      │
      ├──> calculate_unproduced_materials_for_device() ──> [计算在途占用的未出货物料]
      │
      └──> 比对库存: 有效可用 = 物理监控库存 - 在途占用
            │
            ├──> 充足: 返回 200 OK + 明细表 ──> 激活结算按钮
            └──> 不足: 抛出 ValueError ──> 锁定结算按钮并在触控屏标红报警
```

### 2.1 涉及核心文件与函数
- **前端调用**：[`triggerAutoPrecheck()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L918-L937) / [`executeAutoPrecheck()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L940-L965)
- **API 路由**：`POST /api/order/precheck`（`orders/urls.py`）
- **视图层**：[`OrderPrecheckView.post()`](file:///home/ubuntu/autoMachine/automake/orders/views.py#L59-L107)
- **服务层核心函数**：
  1. [`orders.services.precheck_order()`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L204-L428)
  2. [`orders.services.calculate_required_materials()`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L32-L172)
  3. [`orders.services.calculate_unproduced_materials_for_device()`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L174-L202)

---

### 2.2 步骤 1：配方单杯独立核算与耗材纠偏规则
函数 `calculate_required_materials(items_data)` 对商品清单进行计算，并严格遵守以下物理制造规则：
1. **塑料杯不能装热饮**：
   ```python
   # orders/services.py
   is_hot = any(kw in combined_text for kw in ['热', '温', 'hot', 'warm'])
   if is_hot:
       for p_code, paper_target in {'plasticL': 'paperL', 'plasticM': 'paperM'}.items():
           if p_code in single_cup_materials:
               p_qty = single_cup_materials.pop(p_code)
               single_cup_materials[paper_target] = single_cup_materials.get(paper_target, Decimal('0.00')) + p_qty
   ```
2. **纸杯与杯盖成套**：凡使用纸杯（`paperL`/`paperM`），若配方缺失杯盖，自动补齐 `lid` 数量 1：
   ```python
   if has_paper_cup:
       if 'lid' not in single_cup_materials or single_cup_materials['lid'] <= Decimal('0.00'):
           single_cup_materials['lid'] = Decimal('1.00')
   ```
3. **每个杯子都需要封口膜**：无论纸杯还是塑料杯，每杯必须配备 1 张封口膜（`membrane`），缺失则自动补齐数量 1：
   ```python
   if 'membrane' not in single_cup_materials or single_cup_materials['membrane'] <= Decimal('0.00'):
       single_cup_materials['membrane'] = Decimal('1.00')
   ```
4. **单杯独立展开，绝不合并**：
   按购买数量 `quantity` 循环，生成包含每杯独立配料明细的列表，为后续出杯下发制作指令提供精准工步。

---

### 2.3 步骤 2：在途待制作占用量计算 (In-Flight Committed)
函数 `calculate_unproduced_materials_for_device(target_device)` 统计已被其他已支付订单占用、但上位机尚未吐杯完成的物料总量：
```python
# orders/services.py
unproduced_orders = OrderMain.objects.filter(
    device=device,
    status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING] # 待制作与制作中
).prefetch_related('items__skus', 'items__item')
```
遍历这些订单中的商品配方，累加得出当前处于在途占用的物料字典 `unproduced_usage`（如 `{ 'paperL': 3, 'coffee_bean': 45.0, ... }`）。

---

### 2.4 步骤 3：分层介质库存比对与可用量公式
系统根据物料编码将物料分流至不同存储介质进行核算：

$$\text{有效可用库存 (Effective Available)} = \text{物理监控原始库存 (Raw Stock)} - \text{在途待制作占用 (In-Flight)}$$

$$\text{充足判定条件} : \text{有效可用库存} \ge \text{当前订单所需量 (Required)}$$

- **耗材类（MySQL 存储）**：
  读取 `DeviceConsumableStock.objects.filter(device=target_device)`。
  ```python
  cs_obj = consumables_map.get(mat_code)
  db_stock = max(0.0, float(cs_obj.quantity)) if cs_obj else 0.0
  effective_available_stock = db_stock - in_flight_committed
  ```
- **食材类（Redis 存储）**：
  通过 `redis_conn.mget()` 批量读取 `automake:stock:{device_sn}:{code}`。
  ```python
  stock_val = stock_vals.get(mat_code, 0.0)
  effective_available_stock = stock_val - in_flight_committed
  ```

---

### 2.5 步骤 4：校验结果反馈与缺货阻断
- **校验成功**：返回 HTTP 200，并输出每个物料的 `required`、`stock_raw`、`in_flight`、`effective_available` 与 `is_sufficient: true`。上位机据此在右侧表格渲染绿色“🟢 充足”，并激活结算按钮。
- **校验失败**：若任何一项物料不足，`precheck_order()` 抛出 `ValueError` 并附带 `material_checks` 详情列表，视图层返回 `code: 4002`。上位机触控屏在右侧表格将缺料行高亮标红（如 `🔴 缺 1.0个`），并禁用结算按钮（`updateCheckoutButton(false)`），杜绝用户向后流转。

---

## 三、核心重点二：锁库存与并发防超卖实现 (Stock Locking)

为防止多终端或多用户并发支付造成的超卖，系统设计了**双重防护机制**：
1. **微信付款码支付（被扫）**：采用**支付前悲观行锁原子预扣（Pre-lock）**，扣款失败即时回滚；
2. **微信 Native 扫码支付（主扫）**：采用**回调阶段分布式排他锁 + 悲观锁防重扣校验**。

---

### 3.1 付款码支付前原子锁库与即时回滚
在调用微信付款码扣款 API 之前，系统必须先锁定库存。若库存不足，**绝不调用微信扣款接口**！

```
process_codepay_request()
      │
      ├──> try_lock_order_inventory(order)
      │       │
      │       ├──> 1. precheck_device_environment_for_pay(order) [在线状态/硬件快照/排队队列<50]
      │       │
      │       ├──> 2. MySQL 悲观排他行锁:
      │       │       DeviceConsumableStock.objects.select_for_update()
      │       │       检查 quantity >= needed 并原子扣除: cs_obj.quantity -= qty
      │       │
      │       └──> 3. 同步预扣 Redis 耗材: redis_conn.decrby(key, val)
      │
      ├──> 扣库成功 ──> 标记 payment.pay_params['stock_prelocked'] = True
      │                   │
      │                   ▼
      │           WechatPayV3.create_codepay_order() (发起真实微信扣款)
      │                   │
      │       ┌───────────┴───────────┐
      │       ▼ 成功                   ▼ 失败 (密码错误/余额不足/通信异常)
      │ confirm_payment_success()  rollback_order_locked_inventory()
      │ (保留库存，进入制作)         (原子加回 MySQL 与 Redis，释放锁库)
      │
      └──> 扣库失败 ──> 直接返回错误，终止流程 (不产生微信扣款)
```

#### 关键源码实现：
1. **锁定函数**：[`orders.services.try_lock_order_inventory(order)`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L1178-L1277)
   ```python
   # 检查并悲观锁定 MySQL 耗材库存 (select_for_update 锁定行，阻止并发事务读取修改)
   cs_records = {
       cs.code.code: cs
       for cs in DeviceConsumableStock.objects.select_for_update().filter(
           device=device,
           code__code__in=required_cups.keys()
       )
   }
   for cup_code, qty in required_cups.items():
       cs_obj = cs_records.get(cup_code)
       if not cs_obj or cs_obj.quantity < int(qty):
           return False, f"耗材【{cup_code}】库存不足", {}
   
   # 原子扣减 MySQL
   for cup_code, qty in required_cups.items():
       cs_obj = cs_records[cup_code]
       cs_obj.quantity -= int(qty)
       cs_obj.save(update_fields=['quantity', 'updated_at'])

   # 原子扣减 Redis 耗材预扣
   for cup_code, qty in required_cups.items():
       redis_conn.decrby(get_redis_stock_key(device.device_sn, cup_code), int(qty * 100))
   ```
2. **失败回滚函数**：[`orders.services.rollback_order_locked_inventory(order, locked_details)`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L1279-L1315)
   若微信接口返回非 `SUCCESS` 或抛出超时异常，立刻在 `finally` 或异常块中调用此函数：
   ```python
   # 原子累加回写 MySQL
   DeviceConsumableStock.objects.filter(device=device, code__code=cup_code).update(
       quantity=F('quantity') + int(qty), 
       updated_at=timezone.now()
   )
   # 原子恢复 Redis 监控值
   redis_conn.incrby(get_redis_stock_key(device.device_sn, cup_code), int(qty * 100))
   ```

---

### 3.2 支付成功回调防重扣与并发互斥处理
在异步接收微信支付通知（Native 扫码或 JSAPI 支付）时，入口位于 [`payments.services.process_payment_success()`](file:///home/ubuntu/autoMachine/automake/payments/services.py#L704-L1003)：
1. **Redis 分布式锁防穿透**：
   ```python
   lock_key = f"automake:pay_proc_lock:{order_no}"
   acquired = redis_conn.set(lock_key, "1", nx=True, ex=30)
   # 若未获锁，自旋等待另一线程完成，确保幂等
   ```
2. **防重复扣库检测（`is_prelocked`）**：
   ```python
   is_prelocked = bool(payment.pay_params and payment.pay_params.get('stock_prelocked'))
   if not is_prelocked:
       # Native 扫码等未预锁的支付渠道在此处执行 select_for_update 扣除 MySQL 与 decrby 扣除 Redis
       ...
   else:
       logger.info("耗材已在实际支付前原子预锁，跳过重复扣减")
   ```
3. **后置异常冲正补偿**：
   若后续创建生产任务或下发 MQTT 出现不可抗力崩溃，系统捕获异常并在 `except` 块中通过 `redis_conn.incrby()` 执行反向冲正，并自动触发 `refund_order()` 进行退款。

---

## 四、全流程步骤详解

---

### 阶段 1：上位机初始化与测试数据就绪

#### 步骤 1.1：上位机注册在线认证
- **前端操作**：页面加载时自动或点击「终端注册 (sn001)」按钮。
- **前端函数**：[`registerDevice()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L488-L515)
- **网络调用**：`POST /api/device/register`
- **请求体**：
  ```json
  { "device_sn": "sn001", "key_code": "sn001" }
  ```
- **后端函数**：[`DeviceRegisterView.post()`](file:///home/ubuntu/autoMachine/automake/devices/views.py#L185)
- **执行逻辑**：
  1. 校验 `device_sn` 与 `key_code` 匹配性；
  2. 颁发设备级 JWT 访问令牌 `access_token`；
  3. 将设备状态变更为 `online`，更新心跳时间戳。
- **前端响应**：保存 token 至 `localStorage`，顶栏显示“● 设备在线”。

#### 步骤 1.2：注入小额测试菜单与基础库存
- **前端操作**：点击「🌱 注入 0.2元真实测试菜单」。
- **前端函数**：[`seedKioskMenu()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L555-L571)
- **网络调用**：`POST /simulator/api/kiosk/seed_menu/`
- **后端函数**：[`simulator_seed_kiosk_menu_api()`](file:///home/ubuntu/autoMachine/automake/simulator/views.py#L484-L656)
- **执行逻辑**：
  1. 检查并建立基础物料库记录（纸杯、杯盖、膜、咖啡豆、鲜奶、橙汁）；
  2. 初始化 `DeviceConsumableStock`（纸杯 100个、杯盖 100个、封口膜 100张）；
  3. 初始化 Redis 监控键 `automake:stock:sn001:*`（豆 1000g、奶 2000ml、汁 3000ml 等）；
  4. 插入 3 款真实微额商品：浓缩咖啡 (0.01元/1分)、经典拿铁 (0.10元/10分)、鲜榨橙汁 (0.20元/20分)；
  5. 调用 `MenuItem.sync_store_menu(store)` 同步发布至当前门店。

#### 步骤 1.3：实时库存监控 HUD 渲染
- **前端函数**：[`refreshDiagnostics()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L614-L651)
- **网络调用**：`GET /simulator/api/diagnostics/?sn=sn001`
- **后端函数**：[`simulator_diagnostics_api()`](file:///home/ubuntu/autoMachine/automake/simulator/views.py#L378-L467)
- **执行逻辑**：联合查询 MySQL 耗材库存表与 Redis 料桶缓存，返回给前端实时呈现在 HUD 条上。

---

### 阶段 2：点餐选配与下单创建

#### 步骤 2.1：选规格加购与防抖预检
- **前端操作**：在左侧菜品卡片点击「选规格」，选择杯型（大杯/小杯）与温度（热/冷），点击「确认加入购物车」。
- **前端函数**：
  - 打开弹窗：[`openSpecModal(itemId)`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L747-L766)
  - 加购入车：[`confirmAddToCart()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L818-L852)
  - 自动触发预检：[`triggerAutoPrecheck()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L918-L937)
- **网络调用**：`POST /api/order/precheck`
- **后端执行**：[`orders.services.precheck_order()`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L204)
- **业务表现**：
  - 购物车下方即时展现「物料自动校验与可用余量明细表」；
  - 校验通过时结算按钮高亮呈现「去结算出餐 · 真实支付 (￥X.XX)」；
  - 若调用 [`toggleStock('empty', 'paperL')`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L88) 清空纸杯，预检表立即显示“🔴 缺 1.0个”，结算按钮置灰禁用。

#### 步骤 2.2：正式创建订单
- **前端操作**：点击「去结算出餐 · 真实支付」按钮。
- **前端函数**：[`createOrderAndPay()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L1043-L1083)
- **网络调用**：`POST /api/order/create`
- **请求体**：
  ```json
  {
    "store_id": 100000,
    "device_sn": "sn001",
    "items": [{ "item": 12, "sku": [34, 56], "quantity": 1 }],
    "remark": "上位机终端真实下单测试"
  }
  ```
- **后端视图**：[`OrderCreateView.post()`](file:///home/ubuntu/autoMachine/automake/orders/views.py#L109-L154)
- **后端服务**：[`orders.services.create_order()`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L430-L497)
- **执行逻辑**：
  1. 事务内再次执行 `precheck_order()`，防止并发售罄；
  2. 写入主订单表 `OrderMain`（状态设置为 `STATUS_PENDING_PAY`，金额单位：分）；
  3. 写入子明细表 `OrderItem` 并挂接所选 `MenuSku` 规格；
  4. 调用 `record_order_timeline()` 记录订单首个流转事件 `ACTION_CREATE`（订单创建待支付）；
  5. 返回生成的唯一商户订单号 `order_no` 与应付金额 `pay_amount`。
- **前端响应**：前端获取 `order_no`，弹出真实微信收银台窗口 [`openPayModal()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L1088-L1095)。

---

### 阶段 3：双模式微信真实支付与状态确认

收银台提供两种真实扣款途径（单价 ≤ 0.20 元）：

#### 方式 A：Native 扫码支付 (主扫模式)
1. **生成二维码**：
   - **前端函数**：[`generateNativeQR(orderNo)`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L1141-L1185)
   - **网络接口**：`POST /api/pay/wechat/native`
   - **后端视图**：[`PayNativeCreateView.post()`](file:///home/ubuntu/autoMachine/automake/payments/views.py#L140-L175)
   - **后端服务**：[`payments.services.create_native_pay_request()`](file:///home/ubuntu/autoMachine/automake/payments/services.py#L104-L177)
   - **执行逻辑**：
     - 调用 `precheck_device_environment_for_pay(order)` 确保设备在线、健康且排队数 < 50；
     - 调用 `WechatPayV3.create_native_order()` 向微信支付统一下单 API 请求 `code_url`；
     - 创建 `PaymentRecord`（状态 `STATUS_PENDING`，`pay_method='wechat_native'`）；
     - 返回 `code_url` 给前端，前端利用 `qrcode.js` 生成屏幕二维码，启动 90s 倒计时。
2. **状态轮询与异步通知**：
   - 前端启动 [`startPaymentPolling(orderNo)`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L1275-L1291)，每 2 秒调用 `GET /api/pay/status/<order_no>`；
   - 用户使用手机微信“扫一扫”完成真实付款；
   - 微信服务器向后端推送异步回调 `POST /api/pay/callback`。

#### 方式 B：微信付款码支付 (被扫模式)
1. **扫码枪/手动输入扣款**：
   - **前端函数**：[`submitCodePay()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L1223-L1272)
   - **网络接口**：`POST /api/internal/payments/wechat/codepay/`
   - **请求体**：
     ```json
     { "order_no": "202609110001", "auth_code": "134567890123456789", "device_sn": "sn001" }
     ```
   - **后端视图**：[`PayCodePayView.post()`](file:///home/ubuntu/autoMachine/automake/payments/views.py#L177-L226)
   - **后端服务**：[`payments.services.process_codepay_request()`](file:///home/ubuntu/autoMachine/automake/payments/services.py#L180-L320)
   - **执行核心**：
     1. 调用 `try_lock_order_inventory(order)` 执行 MySQL 行级悲观锁锁定与扣减；
     2. 锁定成功后，调用 `WechatPayV3.create_codepay_order()` 发起真实扣款；
     3. 若返回 `SUCCESS`，立即调用 `confirm_payment_success()`；
     4. 若返回 `USERPAYING`，维持库存锁定，前端进入等待输入密码轮询；
     5. 若返回支付失败，立即调用 `rollback_order_locked_inventory()` 原子退还 MySQL 与 Redis 库存。

#### 支付成功后置统一确认核心函数
无论是通过回调、付款码同步成功还是轮询补偿，最终都统一汇聚到核心函数：
[`payments.services.process_payment_success()`](file:///home/ubuntu/autoMachine/automake/payments/services.py#L704-L1003)
1. **加 Redis 分布式排他锁**：防止微信多次重试回调并发穿透；
2. **扣减耗材库存**：若未预锁，执行 `select_for_update` 扣减；
3. **生成订单凭证**：
   - 注入全局唯一制作凭证 UUID：`order.order_token = str(uuid.uuid4())`；
   - 订单状态变更为 `STATUS_PAID`（待出货）；
   - 更新 `PaymentRecord` 为 `STATUS_SUCCESS` 并记录交易号 `transaction_id`；
4. **生成当日递增取餐码**：
   - 调用 [`notifications.services.create_pickup_code(order)`](file:///home/ubuntu/autoMachine/automake/notifications/services.py#L225)；
   - **生成规则**：统计当日已支付订单总数 + 1，格式化为 4 位数字（如 `0001`、`0002`）；
5. **创建生产任务并下发 MQTT 指令**：
   - 调用 [`orders.services.create_production_task(order)`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L508)；
   - 组装标准化 `make` 报文（包含商品名称、取餐号 ticketNo、单杯物料配方清单）；
   - 调用 [`mqtt.issue_make_command()`](file:///home/ubuntu/autoMachine/automake/mqtt/__init__.py#L257) 向硬件广播。

---

### 阶段 4：出单制作与物理出杯履约

```
Django 服务端                          EMQX 代理                       上位机硬件主控
     │                                     │                                │
     ├── issue_make_command() ────────────>│                                │
     │   Topic: s2c/shop/{sn}/state/command│── 推送制作命令 (type: make) ──>│
     │                                     │                                │
     │                                     │                                ├── 启动落杯、磨豆、萃取
     │                                     │<── 上报制作中 (status: making) ──┤
     │<── _handle_device_status() ─────────│                                │
     │    update_order_status('making')    │                                │
     │                                     │                                ├── 封口、出杯传感器检测
     │                                     │<── 上报已完成 (status: done) ───┤
     │<── _handle_device_status() ─────────│                                │
     ├── update_order_status('done')       │                                │
     └── deduct_order_consumables() [扣耗材终态]                             │
```

#### 步骤 4.1：下发 MQTT 制作命令
- **后端函数**：[`mqtt.issue_make_command()`](file:///home/ubuntu/autoMachine/automake/mqtt/__init__.py#L257) -> [`mqtt.issue_device_command()`](file:///home/ubuntu/autoMachine/automake/mqtt/__init__.py#L200)
- **MQTT 主题**：`s2c/shop/{device_sn}/state/command`
- **报文内容**：
  ```json
  {
    "type": "make",
    "order_no": "202609110001",
    "order_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "tradeState": "SUCCESS",
    "ticketNo": "0001",
    "payerTotal": 10,
    "merchInfos": [
      {
        "item_name": "经典拿铁(测试0.10元)",
        "sku_name": "大杯 / 热",
        "quantity": 1,
        "materials": { "paperL": 1, "lid": 1, "membrane": 1, "coffee_bean": 15, "fresh_milk": 150 }
      }
    ]
  }
  ```
- **记录日志**：在 `devices_devicecommand` 表中记录状态为 `sent`，生产任务 `ProductionTask` 更新为 `sent`。

#### 步骤 4.2：接收上位机制作与出杯完成回报
- **硬件上报主题**：`automake/device/{device_sn}/status`
- **MQTT 路由分发**：[`mqtt._on_message()`](file:///home/ubuntu/autoMachine/automake/mqtt/__init__.py#L107) -> [`mqtt._handle_device_status()`](file:///home/ubuntu/autoMachine/automake/mqtt/__init__.py#L164) -> [`devices.views.receive_device_status()`](file:///home/ubuntu/autoMachine/automake/devices/views.py#L30-L180)
- **状态流转分支**：
  1. **上报 `status: "making"`（开始制作）**：
     - 调用 `update_order_status(order, OrderMain.STATUS_MAKING, action=ACTION_MAKING_START)`；
     - 更新 `ProductionTask.status = TASK_MAKING`；
     - 触发异步订单状态通知 `send_order_status_notify()`。
  2. **上报 `status: "done"`（制作完成/物理出杯成功）**：
     - 调用 `update_order_status(order, OrderMain.STATUS_DONE, action=ACTION_MAKING_DONE)`；
     - 更新 `ProductionTask.status = TASK_DONE`，记录 `done_at`；
     - **终态扣减**：调用 [`orders.services.deduct_order_consumables(order)`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L681-L755)，对非杯子类耗材扣除 Redis，并在库存低于 `warn_level` 时通过短信服务报警；
     - 推送取餐就绪通知。
  3. **上报 `status: "failed"`（机械故障/物理卡杯失败）**：
     - 触发明确失败回滚：[`orders.services.process_dispense_failure(order)`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L886-L948)；
     - 订单状态置为 `STATUS_EXCEPTION`；
     - 针对该订单耗用的 Redis 食材执行 `redis_conn.incrby()` 反向补偿补回；
     - 发送失败通知与设备故障告警。

---

### 阶段 5：未制作退款与物料全数放库

为保障用户体验与资金安全，若用户已支付但设备尚未完成物理出杯（状态为 `paid` 或 `making`），上位机触控屏提供了快捷的**退款放库**通道。

```
[用户在触控看板点击退款] 
          │
          ▼
refundCurrentOrder()
          │
          ▼
POST /api/pay/refund (传入 order_no 与 reason)
          │
          ├──> 1. payments.services.refund_order()
          │         ├──> WechatPayV3.apply_refund() [调用微信 APIv3 退款]
          │         ├──> 创建 RefundRecord (记录 refund_id)
          │         └──> 订单状态更新为 REFUNDED
          │
          └──> 2. orders.services.restore_order_inventory()
                    ├──> MySQL 耗材加回: quantity = F('quantity') + qty
                    ├──> Redis 耗材预扣加回: redis_conn.incrby(key, qty*100)
                    ├──> 食材解除在途锁定 (自动从 unproduced_usage 剔除)
                    └──> 生产任务作废: ProductionTask.status = TASK_FAILED
```

#### 步骤 5.1：发起退款放库请求
- **前端操作**：在最新订单看板点击「⚡ 未制作自动退款 (退款放库)」。
- **前端函数**：[`refundCurrentOrder()`](file:///home/ubuntu/autoMachine/automake/simulator/templates/simulator/kiosk.html#L1343-L1409)
- **网络调用**：`POST /api/pay/refund`
- **请求体**：
  ```json
  {
    "order_no": "202609110001",
    "reason": "已支付未制作，触控屏申请退款放库"
  }
  ```
- **后端视图**：[`PayRefundView.post()`](file:///home/ubuntu/autoMachine/automake/payments/views.py#L551-L705)

#### 步骤 5.2：资金原路返还微信
- **服务函数**：[`payments.services.refund_order(order, reason)`](file:///home/ubuntu/autoMachine/automake/payments/services.py#L457-L596)
- **执行逻辑**：
  1. 检索该订单已成功的 `PaymentRecord`；
  2. 生成商户退款单号 `out_refund_no = f"RF-{uuid}"`；
  3. 调用微信支付官方 APIv3 退款网关：`pay_client.apply_refund()`；
  4. 创建 `RefundRecord` 数据记录；
  5. 变更订单主表状态为 `STATUS_REFUNDED`；
  6. 记录时间线日志：`ACTION_REFUND_SUCCESS`（微信退款成功）。

#### 步骤 5.3：物料全数原路放库核心逻辑
- **服务函数**：[`orders.services.restore_order_inventory(order, operator, reason)`](file:///home/ubuntu/autoMachine/automake/orders/services.py#L1024-L1132)
- **放库动作**：
  1. **计算用量**：重新按订单中商品规格解析出所耗费的全部耗材与食材；
  2. **加回 MySQL 耗材库存**：
     ```python
     DeviceConsumableStock.objects.filter(
         device=device,
         code__code=code
     ).update(quantity=F('quantity') + qty_int, updated_at=timezone.now())
     ```
  3. **加回 Redis 耗材预扣值**：
     ```python
     key = get_redis_stock_key(device.device_sn, code)
     redis_conn.incrby(key, int(qty * 100))
     ```
  4. **解冻在途食材锁定**：
     由于订单状态已经变为 `refunded`，在 `calculate_unproduced_materials_for_device` 中自动被排除，其所占用的在途食材配额瞬间释放为可用库存；
  5. **终止关联硬件任务**：
     将未执行的 `ProductionTask` 状态变更为 `TASK_FAILED`，`failure_reason` 标记为退款放库原因，阻止上位机继续制作。
- **返回报告**：
  返回 `restored_materials` 数组（包含归还名称、数量及目标介质），前端看板动态展开显示并在顶部 HUD 即时看到库存数值加回！

---

## 五、全链路函数调用速查总表

| 业务阶段 | 触控屏行为 / 前端函数 | HTTP 接口 / MQTT Topic | 后端 View 类及方法 | 核心业务 Service 函数 | 涉及底层存储 / 状态流转 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **设备注册** | `registerDevice()` | `POST /api/device/register` | `devices.views.DeviceRegisterView.post` | `Device.save()` | `Device.status: online` |
| **菜单注入** | `seedKioskMenu()` | `POST /simulator/api/kiosk/seed_menu/` | `simulator.views.simulator_seed_kiosk_menu_api` | `MenuItem.sync_store_menu()` | `DeviceConsumableStock` (100) / Redis (1000+) |
| **实时监控** | `refreshDiagnostics()` | `GET /simulator/api/diagnostics/` | `simulator.views.simulator_diagnostics_api` | `redis_conn.get()` / `DeviceConsumableStock.objects` | 读取 MySQL 耗材与 Redis 料桶 |
| **库存校验** | `triggerAutoPrecheck()` | `POST /api/order/precheck` | `orders.views.OrderPrecheckView.post` | `orders.services.precheck_order()` | 配方计算、在途扣减、可用量比对 |
| **订单创建** | `createOrderAndPay()` | `POST /api/order/create` | `orders.views.OrderCreateView.post` | `orders.services.create_order()` | `OrderMain` (`pending_pay`) / `OrderStatusLog` (`create`) |
| **扫码发起** | `generateNativeQR()` | `POST /api/pay/wechat/native` | `payments.views.PayNativeCreateView.post` | `payments.services.create_native_pay_request()` | `PaymentRecord` (`pending`) / 微信 Native API |
| **付款码支付** | `submitCodePay()` | `POST /api/internal/payments/wechat/codepay/` | `payments.views.PayCodePayView.post` | `payments.services.process_codepay_request()` | `try_lock_order_inventory()` 悲观锁行扣库 |
| **支付回调** | 微信服务器推送 | `POST /api/pay/callback` | `payments.views.PayCallbackView.post` | `payments.services.process_payment_success()` | `PaymentRecord` (`success`), `OrderMain` (`paid`) |
| **取餐码生成** | 支付成功触发 | 内部服务调用 | - | `notifications.services.create_pickup_code()` | 生成当日自增取餐码 (如 `0001`) |
| **任务派发** | 支付成功触发 | `s2c/shop/{sn}/state/command` | - | `orders.services.create_production_task()` + `mqtt.issue_make_command()` | `ProductionTask` (`sent`), MQTT 下发 |
| **制作中回调** | 硬件上报 MQTT | `automake/device/{sn}/status` | `devices.views.receive_device_status` | `orders.services.update_order_status()` | `OrderMain` (`making`), `ProductionTask` (`making`) |
| **出杯完成** | 硬件上报 MQTT | `automake/device/{sn}/status` | `devices.views.receive_device_status` | `orders.services.update_order_status()` + `deduct_order_consumables()` | `OrderMain` (`done`), 扣减耗材终态, 短信报警 |
| **出杯失败** | 硬件故障上报 | `automake/device/{sn}/status` | `devices.views.receive_device_status` | `orders.services.process_dispense_failure()` | `OrderMain` (`failed`), Redis 反向补偿 `incrby` |
| **未制作退款** | `refundCurrentOrder()` | `POST /api/pay/refund` | `payments.views.PayRefundView.post` | `payments.services.refund_order()` | 调用微信 APIv3 退款，`OrderMain` (`refunded`) |
| **退款放库** | 退款同步触发 | `POST /api/pay/refund` | `payments.views.PayRefundView.post` | `orders.services.restore_order_inventory()` | `DeviceConsumableStock` 加回, Redis 加回, 任务作废 |

---
*文档编制完成于 2026 年，适用于智能咖啡上位机系统及对应 Django 后端架构。*
