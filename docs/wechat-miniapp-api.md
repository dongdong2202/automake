# AutoMachine 微信小程序 API 对接文档

> 认证方式：JWT Bearer Token｜金额单位：分（整数）｜数据格式：application/json

---

## 一、通用规则

**基础地址**：`https://yourdomain.com`（本地调试用 `http://127.0.0.1:8000`）

**所有响应格式统一**：
```json
{ "code": 0, "message": "ok", "data": { ... } }
```
`code=0` 成功，非 0 为业务错误，`data=null` 时看 `message`。

**需要登录的接口**，请求 Header 加：
```
Authorization: Bearer <access_token>
```

---

## 二、快速封装请求（复制即用）

```javascript
// utils/request.js
const BASE = 'https://yourdomain.com';

function request(method, path, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE + path,
      method,
      data,
      header: {
        'content-type': 'application/json',
        'Authorization': 'Bearer ' + (wx.getStorageSync('access_token') || '')
      },
      success: res => {
        if (res.statusCode === 401) {
          // Token 过期 → 引导重新登录
          wx.redirectTo({ url: '/pages/login/login' });
          return;
        }
        resolve(res.data);
      },
      fail: err => {
        wx.showToast({ title: '网络异常', icon: 'none' });
        reject(err);
      }
    });
  });
}

module.exports = { request };
```

---

## 三、完整下单流程

```
wx.login() → 登录换 Token → 选门店 → 看菜单 → 预校验 → 创建订单 → 支付 → 轮询完成
```

---

## 四、接口一览

### 1. 微信登录（换取 JWT Token）
```
POST /api/user/login
```
```json
// 请求
{ "code": "wx.login()返回的code", "nickname": "可选", "avatar_url": "可选" }

// 响应
{
  "code": 0,
  "data": {
    "access": "eyJ...",    // 有效期 2 小时，接口鉴权用
    "refresh": "eyJ...",   // 有效期 30 天，用于刷新 access
    "user": { "id": 1, "role": "customer", "profile": { "nickname": "张三", "points": 0 } }
  }
}
```
```javascript
// 调用示例
wx.login({
  success({ code }) {
    wx.request({
      url: BASE + '/api/user/login',
      method: 'POST',
      header: { 'content-type': 'application/json' },
      data: { code },
      success(res) {
        if (res.data.code === 0) {
          wx.setStorageSync('access_token', res.data.data.access);
          wx.setStorageSync('refresh_token', res.data.data.refresh);
        }
      }
    });
  }
});
```

---

### 2. 刷新 Token
```
POST /api/user/token/refresh
```
```json
// 请求
{ "refresh": "eyJ..." }

// 响应（直接返回，无外层包装）
{ "access": "eyJ...", "refresh": "eyJ..." }
```

---

### 3. 用户资料
```
GET  /api/user/profile        → 查看资料（需登录）
PUT  /api/user/profile        → 更新资料（需登录）
```
```json
// PUT 请求体（字段可选）
{ "nickname": "李四", "avatar_url": "https://..." }
```

---

### 4. 门店列表（无需登录）
```
GET /api/store/list
```
```json
// 响应 data 为数组
[{ "id": 1, "name": "旗舰店", "address": "...", "lat": "39.9", "lng": "116.4", "status": "open" }]
```
> `status`: `open`=营业 / `closed`=关闭 / `paused`=暂停

---

### 5. 门店菜单（无需登录）
```
GET /api/menu/store/{store_id}
```
```json
// 响应结构：分类 → 商品 → SKU
{
  "store_id": 1,
  "store_name": "旗舰店",
  "categories": [{
    "id": 1, "name": "热饮",
    "items": [{
      "id": 1, "name": "精品拿铁", "base_price": 2800,
      "skus": [
        { "id": 1, "name": "中杯", "price_delta": 0,   "final_price": 2800 },
        { "id": 2, "name": "大杯", "price_delta": 500,  "final_price": 3300 }
      ]
    }]
  }]
}
```
> 金额单位均为**分**，展示时除以 100：`(2800/100).toFixed(2)` → `"28.00"`

---

### 6. 预校验（下单前调用）
```
POST /api/order/precheck      需登录
```
```json
// 请求
{
  "store_id": 1,
  "items": [
    { "sku_id": 1, "quantity": 1 },
    { "sku_id": 2, "quantity": 2 }
  ],
  "remark": "少糖"
}
```
```json
// 响应
{ "code": 0, "data": { "pay_amount": 9400, "total_amount": 9400, "items": [...] } }
```
> 通过后展示结算页，让用户确认，再调创建订单。

---

### 7. 创建订单
```
POST /api/order/create        需登录
```
> 请求体与预校验相同。
```json
// 响应
{ "code": 0, "data": { "order_no": "20260609143022123456", "pay_amount": 9400, "status": "pending_pay" } }
```

---

### 8. 发起支付
```
POST /api/pay/create          需登录
```
```json
// 请求
{ "order_no": "20260609143022123456" }

// 响应
{ "code": 0, "data": { "appId": "wx...", "timeStamp": "...", "nonceStr": "...", "package": "prepay_id=...", "signType": "RSA", "paySign": "..." } }
```
```javascript
// 拿到 data 后直接调起支付
const res = await request('POST', '/api/pay/create', { order_no: orderNo });
if (res.code === 0) {
  wx.requestPayment({
    ...res.data,
    success() { /* 跳转订单状态页，开始轮询 */ },
    fail(err)  { wx.showToast({ title: err.errMsg.includes('cancel') ? '已取消' : '支付失败', icon: 'none' }); }
  });
}
```

---

### 9. 订单状态轮询
```
GET /api/order/{order_no}     需登录
```
```json
// 响应关键字段
{ "status": "making", "status_display": "制作中", "paid_at": "...", "done_at": null }
```

| status | 说明 |
|--------|------|
| `pending_pay` | 待支付 |
| `paid` | 已支付，等待制作 |
| `making` | 制作中 |
| `done` | 已完成，可取杯 ✅ |
| `exception` | 异常，联系客服 |

```javascript
// 支付成功后开始轮询（每 3 秒，最多 2 分钟）
let count = 0;
const timer = setInterval(async () => {
  if (++count > 40) { clearInterval(timer); return; }
  const res = await request('GET', `/api/order/${orderNo}`);
  if (res.data?.status === 'done') {
    clearInterval(timer);
    wx.showToast({ title: '请取杯！', icon: 'success' });
  }
}, 3000);
```

---

### 10. 我的订单列表
```
GET /api/order/list           需登录
```
```json
// 响应 data 为数组
[{ "order_no": "...", "status": "done", "status_display": "已完成", "pay_amount": 9400, "item_count": 3, "created_at": "..." }]
```

---

## 五、主要错误码

| code | 说明 |
|------|------|
| `1002` | 微信 code 无效（已过期或重复使用）|
| `2001` | 门店不存在 |
| `3002` | 门店暂未营业 |
| `4002` | 预校验失败（商品下架、无可用设备等）|
| `5003` | 支付发起失败 |

---

## 六、注意事项

1. **HTTPS**：上线必须用 HTTPS，并在微信公众平台配置合法域名。本地调试勾选"不校验合法域名"。
2. **Token 存储**：用 `wx.setStorageSync` 存 access/refresh token，不要放 URL 参数。
3. **金额**：所有价格均为**分（整数）**，展示时自行除以 100。
4. **code 一次性**：`wx.login()` 的 code 只能用一次，且 5 分钟内有效。
