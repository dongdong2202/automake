# 数据表、函数与接口关系说明

## 1. 文档目的

本文不再重复功能定义、数据表定义或接口定义，只说明三者之间的 **关系**：
- 先后顺序
- 谁调用谁
- 谁依赖谁
- 数据从哪里来，到哪里去

目标是让阅读者快速看懂：**一个业务动作发生时，哪些接口会被调用，哪些函数会执行，哪些表会被写入或读取，以及服务器、微信端、上位机之间如何串联。**

---

## 2. 总体关系图

```text
微信端/本地点餐端
    ↓ 调用 HTTPS API
服务器接口层（Nginx → Django API）
    ↓ 调用
服务器业务函数层
    ↓ 读写
MySQL / Redis
    ↓ 触发
设备命令下发函数
    ↓ 通过 MQTT/HTTPS
上位机服务
    ↓ 调用
下位机执行控制
    ↓ 回传状态
服务器状态处理函数
    ↓ 更新
订单表 / 设备表 / 日志表 / 告警表
    ↓ 返回
微信端订单状态、消息通知、看板数据
```

这个总关系里有四条主线：
1. 用户下单线
2. 支付确认线
3. 设备执行线
4. 状态回传线

---

## 3. 关系一：微信端与服务器之间

### 3.1 登录关系

```text
微信端 wxLogin()
    ↓
服务器接口 /api/user/login
    ↓
服务器函数 login_by_wechat(code)
    ↓
读取/写入 user, user_profile
    ↓
返回 token, user_id, member_info
    ↓
微信端保存 token
```

关系说明：
- `wxLogin()` 是微信端动作起点。
- `/api/user/login` 是微信端调用的接口。
- `login_by_wechat(code)` 是服务器内部真正处理登录逻辑的函数。
- `user`、`user_profile` 是该函数直接依赖的数据表。
- 没有 token，后续大多数接口都不能调用，因此 **登录关系是其它用户业务关系的前置依赖**。

### 3.2 选店与拉菜单关系

```text
微信端 fetchStoreList()
    ↓
服务器接口 /api/store/list
    ↓
服务器函数 list_stores(location)
    ↓
读取 store
    ↓
返回门店列表

微信端 fetchMenu(store_id)
    ↓
服务器接口 /api/menu/store/{store_id}
    ↓
服务器函数 get_store_menu(store_id)
    ↓
读取 store, menu_category, menu_item, menu_sku, menu_price_rule
    ↓
返回菜单、规格、价格、库存可售状态
```

关系说明：
- `fetchStoreList()` 先于 `fetchMenu()`，因为菜单依赖门店上下文。
- `get_store_menu(store_id)` 依赖门店信息和菜单相关表。
- 如果门店状态不可用，菜单接口应直接终止，因此 **门店表是菜单读取的前置依赖**。

### 3.3 购物车与预下单关系

```text
微信端 updateCart()
    ↓
本地内存 cartItems 更新
    ↓
微信端 precheckOrder(cartItems)
    ↓
服务器接口 /api/order/precheck
    ↓
服务器函数 precheck_order(payload)
    ↓
读取 menu_item, menu_sku, material_stock, device, store_device
    ↓
调用 lock_inventory(order_items)（可选：预锁）
    ↓
返回可售结果、价格、预计等待信息
```

关系说明：
- 购物车更新通常先在前端本地发生，不一定马上写服务器。
- `precheck_order(payload)` 是正式下单前的依赖判断函数。
- 这个函数依赖商品、库存、设备、门店设备映射信息。
- 如果预校验失败，则不会进入 `create_order()`，因此 **预校验是订单创建的直接前置步骤**。

---

## 4. 关系二：订单、支付、库存之间

### 4.1 创建订单关系

```text
微信端 submitOrder(payload)
    ↓
服务器接口 /api/order/create
    ↓
服务器函数 create_order(payload)
    ↓
依赖 precheck_order(payload) 已成功
    ↓
写入 order_main
    ↓
写入 order_item
    ↓
写入 order_status_log(待支付)
    ↓
调用 lock_inventory(order_items)
    ↓
返回 order_no
```

关系说明：
- `create_order(payload)` 不能脱离 `precheck_order(payload)` 单独理解。
- `order_main` 是主表，`order_item` 依赖 `order_main`，因此先写主表再写明细。
- `order_status_log` 依赖订单编号，因此在订单生成后写入第一条状态记录。
- `lock_inventory(order_items)` 在时间上紧跟订单创建，作用是保证支付过程中的库存有效性。

### 4.2 发起支付关系

```text
微信端 createWechatPay(order_no)
    ↓
服务器接口 /api/pay/create
    ↓
服务器函数 create_pay_request(order_no)
    ↓
读取 order_main, order_item
    ↓
写入 payment_record(待支付)
    ↓
返回 pay_params
    ↓
微信端 invokeWechatPay(pay_params)
```
1
关系说明：
- 支付请求依赖订单已创建，所以 `create_pay_request(order_no)` 的前置条件是 `order_main` 中已有有效订单。
- `payment_record` 是支付流程的主记录表，依赖 `order_no`。
- 如果订单状态不是“待支付”，支付接口应拒绝执行，因此 **订单状态是支付接口的判断依赖**。

### 4.3 微信支付回调关系

```text
微信服务器异步通知
    ↓
服务器接口 /api/pay/callback
    ↓
服务器函数 verify_pay_callback(callback_body)
    ↓
写入 payment_callback_log
    ↓
调用 process_payment_success(order_no)
    ↓
更新 payment_record(已支付)
    ↓
更新 order_main(已支付)
    ↓
写入 order_status_log(已支付)
    ↓
调用 create_production_task(order_no)
    ↓
更新 material_stock / 或确认库存扣减
    ↓
调用 issue_make_command(order_no, device_id)
```

关系说明：
- `verify_pay_callback()` 是回调入口函数，只负责验签、校验、幂等判断。
- `process_payment_success(order_no)` 是成功后的业务处理函数，它依赖回调验签成功。
- `payment_callback_log` 先落库，再做业务处理，便于审计与排错。
- 只有支付成功后，订单才会进入生产链路，因此 **支付成功是生产任务创建的直接前置条件**。

---

## 5. 关系三：服务器与上位机之间

### 5.1 设备初始化关系

```text
上位机 startup_sync()
    ↓
服务器接口 /api/device/register
    ↓
服务器函数 register_device(device_payload)
    ↓
写入/更新 device
    ↓
写入 device_status_log(初始化上线)
    ↓
返回 device_id, config, resource_version
    ↓
上位机 pull_menu_resource()
    ↓
服务器接口 /api/device/resource/pull
    ↓
服务器函数 sync_resource_package()
    ↓
读取 menu_category, menu_item, menu_sku, resource_asset, system_config
    ↓
上位机写入 local_resource_version, local_menu_cache
```

关系说明：
- `startup_sync()` 是上位机启动时的总入口函数。
- `register_device()` 先于 `pull_menu_resource()`，因为设备必须先在云端有身份，才能拉取资源。
- 云端 `device` 表和上位机本地 `local_resource_version`、`local_menu_cache` 构成云边同步关系。
- 资源同步依赖门店、菜单、资源表，因此 **资源表是边缘初始化的直接数据来源**。

### 5.2 云端下发出杯命令关系

```text
服务器函数 create_production_task(order_no)
    ↓
写入 production_task
    ↓
服务器函数 issue_make_command(order_no, device_id)
    ↓
写入 device_command(待发送)
    ↓
通过 EMQX 发送 MQTT 消息
    ↓
上位机函数 accept_order_task(orderPayload)

```

关系说明：
- `production_task` 是订单进入生产领域后的主记录。
- `device_command` 是云端命令表，记录“要发什么命令给哪台设备”。
- `accept_order_task()` 是上位机接收云端任务的入口。


---

## 6. 关系四：上位机、服务器之间的状态回传关系

### 6.1 订单状态回传关系

```text

上位机 mark_order_making(orderNo)
    ↓
上位机 report_order_status(orderNo, 制作中)
    ↓
服务器接口 /api/device/order/status/report
    ↓
服务器函数 receive_device_status(payload)
    ↓
更新 order_main.status
    ↓
写入 order_status_log
    ↓
更新 queue_snapshot（可选）
    ↓
微信端 pollOrderStatus(orderNo) / WSS 订阅接收
```

```text
上位机 mark_order_done(orderNo)
    ↓
上位机 report_order_status(orderNo, 完成)
    ↓
服务器接口 /api/device/order/status/report
    ↓
服务器函数 receive_device_status(payload)
    ↓
更新 order_main.status = 完成
    ↓
写入 order_status_log(完成)
    ↓
调用 send_user_notify(user_id, 出杯完成)
    ↓
写入 notify_event / message_box
    ↓
微信端看到订单完成消息
```

关系说明：
- 状态变化先发生在下位机/上位机，再同步给服务器。
- `receive_device_status(payload)` 是服务器处理状态回传的统一入口。
- `order_main` 存当前状态，`order_status_log` 存状态历史，因此两者不是重复关系，而是“当前值 + 历史轨迹”的关系。
- 微信端查看到的订单状态，依赖服务器已成功更新订单表，因此 **用户可见状态依赖设备回传成功**。

### 6.2 设备状态回传关系

```text
上位机 report_device_status(data)
    ↓
服务器接口 /api/device/status/report
    ↓
服务器函数 save_device_heartbeat(device_id) / receive_device_status(payload)
    ↓
更新 device
    ↓
写入 device_status_log
    ↓
数据看板读取 device, device_status_log
```

关系说明：
- `device` 表记录设备最新状态。
- `device_status_log` 记录状态变化历史。
- 看板展示“在线率、故障率、离线次数”时，既依赖当前表，也依赖历史表。

### 6.3 物料上报关系

```text
上位机 collect_material_state()
    ↓
上位机 report_material_state(data)
    ↓
服务器接口 /api/device/material/report
    ↓
服务器函数 receive_material_report(payload)
    ↓
更新 material_stock
    ↓
写入 material_change_log / material_log
    ↓
如低于阈值，调用 create_alarm_event(payload)
    ↓
写入 device_alarm / alarm_event
    ↓
消息中心 send_notify()
```

关系说明：
- 物料状态先由上位机采集，再上报云端。
- `material_stock` 是当前量，`material_change_log` 是变化记录。
- 告警逻辑依赖物料阈值判断，因此 **告警表依赖物料表更新结果**。

---

## 7. 关系五：异常、告警之间


### 7.1 异常与告警关系

```text
订单失败 / 设备异常 / 物料不足 / 断网断电
    ↓
服务器函数 handle_make_failed() / create_alarm_event(payload)
    ↓
写入 exception_event
    ↓
写入 alarm_event 或 device_alarm
    ↓
调用 send_notify()
    ↓
写入 notify_event, message_box
    ↓
后台或微信端看到异常消息
```

关系说明：
- `exception_event` 更偏“异常事实记录”。
- `alarm_event` / `device_alarm` 更偏“需要告警处理”的事件。
- `notify_event` / `message_box` 更偏“把异常告诉谁”。
- 因此三者不是同一层概念，而是 **异常记录 → 告警生成 → 通知送达** 的先后关系。

---

## 8. 关系六：数据看板与业务表之间

### 8.1 看板统计关系

```text
定时任务 build_dashboard_metrics(date)
    ↓
读取 order_main, payment_record, refund_record, device, device_status_log, material_stock
    ↓
聚合计算
    ↓
写入 dashboard_metric / finance_daily / profit_stat
    ↓
后台接口 /api/dashboard/overview
    ↓
后台页面读取图表数据
```

关系说明：
- 看板表不是业务起点，而是业务结果汇总。
- `dashboard_metric` 依赖订单、支付、退款、设备、物料等基础业务表。
- 如果基础表数据异常，看板一定异常，因此 **看板表是典型的下游依赖表**。

---

## 9. 时间先后关系总结

### 9.1 用户下单主链路的时间顺序

```text
1. wxLogin()
2. fetchStoreList()
3. fetchMenu(store_id)
4. updateCart()
5. precheckOrder(cartItems)
6. create_order(payload)
7. create_pay_request(order_no)
8. 微信支付
9. verify_pay_callback()
10. process_payment_success(order_no)
11. create_production_task(order_no)
12. issue_make_command(order_no, device_id)
13. accept_order_task(orderPayload)
14. dispatch_make_command(orderNo)
15. send_to_device(command)
16. report_order_status(orderNo, 制作中)
17. report_order_status(orderNo, 完成)
18. send_user_notify(user_id)
19. 微信端看到完成状态/消息
```

这条顺序说明：
- 前 1 到 8 是“用户交易阶段”。
- 9 到 12 是“云端确认并转入生产阶段”。
- 13 到 17 是“边缘执行阶段”。
- 18 到 19 是“结果反馈阶段”。

### 9.2 上位机启动链路的时间顺序

```text
1. startup_sync()
2. register_to_cloud()
3. pull_menu_resource()
4. sync_runtime_config()
5. 本地写入 local_resource_version / local_menu_cache
6. 等待云端任务
7. 接收订单命令
8. 执行并上报状态
```

这条顺序说明：
- 注册先于资源同步。
- 资源同步先于接单执行。
- 本地缓存建立先于断网可用能力。

---

## 10. 依赖关系总结

### 10.1 表之间依赖

```text
user → user_profile
store → menu_category/menu_item/menu_sku
order_main → order_item
order_main → order_status_log
order_main → payment_record
order_main → production_task
device → device_status_log
device → device_command
material_stock → material_change_log
alarm_event → notify_event/message_box
```

说明：
- 左边通常是主实体，右边是附属记录或流水记录。
- 主实体不存在，附属记录通常不能单独存在。

### 10.2 函数之间依赖

```text
login_by_wechat() → 后续所有需鉴权函数
precheck_order() → create_order()
create_order() → create_pay_request()
verify_pay_callback() → process_payment_success()
process_payment_success() → create_production_task()
create_production_task() → issue_make_command()
accept_order_task() → dispatch_make_command()
dispatch_make_command() → send_to_device()
report_order_status() → receive_device_status()
receive_device_status() → send_user_notify()
receive_material_report() → create_alarm_event()
```

说明：
- 箭头不是“唯一调用关系”，而是“核心依赖关系”。
- 前一个函数结果不成立，后一个函数通常不能正确执行。

### 10.3 接口之间依赖

```text
/api/user/login
    ↓
/api/store/list
    ↓
/api/menu/store/{store_id}
    ↓
/api/order/precheck
    ↓
/api/order/create
    ↓
/api/pay/create
    ↓
/api/pay/callback
    ↓
/api/device/order/status/report
```

说明：
- 用户接口先于设备接口。
- 支付成功接口是用户交易域与设备生产域之间的分界点。

---

## 11. 一句话理解整套关系

可以把整套系统理解成下面这条链：

```text
微信端发起业务 → 服务器接口接收 → 服务器函数处理 → MySQL/Redis 落数据 → 云端命令发给上位机 → 上位机回传状态 → 服务器更新订单/设备/日志/告警 → 微信端与后台看到结果
```

如果只抓最关键的关系，则是：

```text
订单是主线，支付是分界点，生产任务是桥梁，设备状态回传是闭环。
```




 ### 1. 完成的工作与变更详情                                                                                                                                                  
                                                                                                                                                                               
  • 模拟类实现：在 client.py 下创建了  UpperMachineSimulator  类：                                                                                                        
      • 点单端模拟：实现了内存购物车（Cart），支持添加/减少商品；向服务器发送 HTTPS 请求完成订单预校验 (precheck) 和创建订单 (create)；                                        
      • 加密支付回调：根据微信支付 APIv3 协议与本机的  .env  配置，通过本地 AEAD_AES_256_GCM 加密，完全真实模拟向  /api/pay/callback  投递支付成功回调包；
      • 上位机客户端模拟：支持 HTTPS 设备注册；后台启动 MQTT 客户端，定时发送 online 心跳上报至服务器，并订阅/监听云端制作命令；
      • 库存控制与异常管理：当上位机收到 "make" 指令时，异步触发 HTTPS 锁库存 → 上报进度 → HTTPS 扣减实际库存/或在强制异常时 HTTPS 释防已锁定库存 → 上报出杯或制作失败状态。   
  • 后端新增 API 支持：为支持模拟器的锁库存和扣库存调用，在  MaterialStock  模型中添加了  locked_quantity  字段并生成迁移，在 views.py 和 urls.py 
  中新增并注册了以下三个 HTTP 接口：
      •  POST /api/device/inventory/lock  (锁定物料库存)
      •  POST /api/device/inventory/deduct  (扣减实际物料库存)
      •  POST /api/device/inventory/release  (释防锁定物料库存)
  • 一键初始化数据脚本：创建了 seed.py 脚本，可快速初始化门店、菜单（美式与拿铁）、设备 SN001 及其对应的初始物料库存（咖啡豆与牛奶），方便直接运行模拟器演示。          
  • 修复并使所有单元测试通过：补充了被注释的弃用心跳和订单上报 HTTP 占位视图，解决了原本  manage.py test simulator  的测试失败，目前所有测试结果为 OK。
  
  ### 2. 查看详细设计与时序图
  
  有关详细的时序图、接口参数设计和交互流，请阅读生成的文档：simulator_docs.md。
  
  ### 3. 如何在终端中运行 Demo
  
  1. 初始化测试数据（如您想清空/重置库存至 100%）：
    export DJANGO_SETTINGS_MODULE=default.settings
    export PYTHONPATH=.
    /home/ubuntu/autoMachine/.venv1/bin/python /home/ubuntu/autoMachine/automake/simulator/seed.py
  
  2. 运行一键流程模拟：
    /home/ubuntu/autoMachine/.venv1/bin/python /home/ubuntu/autoMachine/automake/simulator/client.py




    python manage.py makemigrations
    python manage.py migrate



