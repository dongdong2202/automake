
---

```markdown
# 订单与智能终端（上位机）库存协同系统架构设计规范

## 1. 角色与数据边界定义 (Role & Data Boundaries)

这是购物车的json格式：
cartjson = '''[{item:3, sku:[6,7]}, {item:1, sku:[3,4,5]}]'''
item是在门店的菜单里，可以获取到基础价格
sku是门店的商品规格表，可以获取用量和delta价格，注意item 也要关联到sku表里以获得用料
* **云端服务器 (Server)**：
    * 管理**账面虚拟库存 (Virtual Stock)**（基于 Redis 缓存）。
    * 处理高并发用户下单请求，执行初步过滤（PreCheck）。
    * 持久化订单状态，维护全局交易流水。
* **上位机/硬件终端 (Host Computer/Edge Device)**：
    * 管理**实物实际库存 (Physical Stock)**。它是整个系统库存的**最终真理源 (Source of Truth)**。
    * 控制物理机械结构执行出库操作。
    * 定期或在变动时向服务器同步物理库存。

---

## 2. 状态机定义 (State Machines)

### 2.1 订单状态 (Order Status)
AI 在编写代码时必须严格遵循以下状态流转，禁止跨状态跳跃：
* `CREATED`：订单已创建，尚未扣减虚拟库存。
* `PENDING_DISPENSE`：云端虚拟库存预扣成功，指令已下发，等待上位机物理出库。
* `SUCCESS`：上位机回报出库成功，订单最终完成。
* `FAILED`：物理出库失败或超时，触发资产冲正回滚后的最终失败状态。
* `CANCELLED`：用户主动取消或超时未支付。

### 2.2 库存概念 (Inventory Concepts)
* `Redis_Available_Stock`：允许下单的可用额度。
* `DB_Book_Stock`：数据库记录的账面库存。
* `Physical_Actual_Stock`：上位机硬件中实际存在的物理货品数量。

---

## 3. 核心业务流程与伪代码逻辑 (Core Workflows)

### 3.1 阶段一：库存同步 (基准线)
* **触发时机**：上位机定时（如每5分钟）或物理补货/清料时。
* **逻辑**：上位机上报 `Physical_Actual_Stock` -> 服务器直接覆盖 `Redis_Available_Stock` 并在 DB 中更新基准。

### 3.2 阶段二：高并发下单与预扣 (PreCheck & Lock)
当用户发起下单请求时，服务器必须**严格按以下顺序**执行，严禁将步骤调换：

1.  **Redis 原子预扣 (Lua 脚本)**：
    AI 必须实现以下 Lua 脚本逻辑以确保并发安全：
    ```lua
    local stock = tonumber(redis.call('get', KEYS[1]) or "0")
    local num = tonumber(ARGV[1])
    if stock >= num then
        redis.call('decrby', KEYS[1], num)
        return 1 -- 成功
    else
        return 0 -- 库存不足
    end
    ```
2.  **DB 订单持久化**：
    * 若 Redis 返回 0，立即抛出业务异常（库存不足），不操作数据库。
    * 若 Redis 返回 1，在数据库中插入订单，并生成全局唯一 `OrderToken`（UUID/Snowflake）。
    * **初始状态** 必须设置为 `PENDING_DISPENSE`。
3.  **指令下发**：通过 MQTT/WebSocket 向对应上位机发送出库指令，数据包必须包含 `OrderToken` 和 `Quantity`。

### 3.3 阶段三：上位机执行与回调 (Dispense & Callback)
1.  **上位机幂等校验**：
    * 上位机收到指令后，必须检查本地 `ExecutedTokens` 历史。若 `OrderToken` 已存在，直接丢弃或返回历史结果，防止因网络重试导致二次出库。
2.  **物理出库**：硬件驱动吐货。
3.  **结果回报**：
    * **出库成功**：上位机上报 `SUCCESS`。服务器更新 DB 订单状态为 `SUCCESS`。
    * **出库失败**：上位机上报 `DISPENSE_FAILED`（如机械卡死），进入异常恢复流程。

---

## 4. 异常恢复与防死锁设计 (Exception Handling & Rollback)

AI 在编写异常处理模块时，必须实现以下两个原子回滚机制：

### 4.1 明确失败回滚 (Explicit Failure Rollback)
* **场景**：收到上位机明确上报的 `DISPENSE_FAILED`。
* **代码执行要求**：
    1.  开启 DB 事务，将订单状态由 `PENDING_DISPENSE` 变更为 `FAILED`。
    2.  利用乐观锁将 DB 库存加回：`UPDATE inventory SET stock = stock + :qty WHERE id = :id`。
    3.  **反向补偿 Redis**：执行 `redis.call('incrby', key, qty)`。

### 4.2 超时未决与对账挂起 (Timeout & Reconciliation)
* **场景**：指令下发后，由于网络闪断，服务器在 30 秒内未收到上位机的任何回调。
* **代码执行要求**：
    1.  **严禁自动失败或成功**。订单状态保持 `PENDING_DISPENSE`。
    2.  **触发熔断**：服务器暂停向该上位机下发新订单。
    3.  **断线重连对账**：当上位机重新连接时，必须主动发起 `ReconciliationRequest`，携带本地最后执行的 Token 日志。服务器对比状态为 `PENDING_DISPENSE` 的订单，进行最终的状态同步（冲正或确认）。

---

## 5. AI 编码质量约束 (Coding Guardrails)

* **幂等性**：所有面向硬件的接口、以及硬件回报的接口，必须通过 `OrderToken` 实现强幂等。
* **数据库锁**：数据库库存更新必须使用乐观锁扣减（`WHERE stock >= qty`），严禁使用带 `FOR UPDATE` 的大事务锁表。
* **日志记录**：在 Redis 预扣、指令下发、硬件回调、异常回滚 4 个核心节点，必须输出包含 `OrderToken` 的结构化日志（JSON 格式），以便于全链路追踪。

```