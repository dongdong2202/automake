<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-left">
        <div class="brand-content">
          <el-icon class="brand-icon"><CoffeeCup /></el-icon>
          <h1 class="brand-title">AutoMake 智能制造</h1>
          <p class="brand-desc">自助现磨咖啡·智能运营·销售与财务一体化管理系统</p>
          <div class="brand-features">
            <div class="feature-item">
              <el-icon><DataAnalysis /></el-icon>
              <span>实时全维监控与数据看板</span>
            </div>
            <div class="feature-item">
              <el-icon><Cpu /></el-icon>
              <span>设备状态毫秒级云边互通</span>
            </div>
            <div class="feature-item">
              <el-icon><TakeawayBox /></el-icon>
              <span>智能进销存与物料预警预测</span>
            </div>
          </div>
        </div>
      </div>

      <div class="login-right">
        <div class="form-wrapper">
          <h2 class="form-title">运营管理后台登录</h2>
          <p class="form-subtitle">直接服务超级管理员、店长及物料员</p>

          <el-form
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            size="large"
            @keyup.enter="handleLogin"
          >
            <el-form-item prop="username">
              <el-input
                v-model="loginForm.username"
                placeholder="请输入用户名"
                :prefix-icon="User"
                clearable
              />
            </el-form-item>

            <el-form-item prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="请输入密码"
                :prefix-icon="Lock"
                show-password
                clearable
              />
            </el-form-item>

            <div class="remember-row">
              <el-checkbox v-model="rememberMe">记住账号</el-checkbox>
              <span class="tip-text">忘记密码请联系超级管理员</span>
            </div>

            <el-form-item>
              <el-button
                type="primary"
                :loading="loading"
                class="submit-btn"
                @click="handleLogin"
              >
                登 录 运 营 平 台
              </el-button>
            </el-form-item>
          </el-form>

          <div class="login-footer">
            <p>技术支持：AutoMake 智能制造 IoT 研发团队</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { User, Lock, CoffeeCup, DataAnalysis, Cpu, TakeawayBox } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const loginFormRef = ref<FormInstance>()
const loading = ref(false)
const rememberMe = ref(true)

const loginForm = reactive({
  username: localStorage.getItem('remember_username') || '',
  password: '',
})

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入运营管理员用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  if (!loginFormRef.value) return
  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await authStore.login({
        username: loginForm.username,
        password: loginForm.password,
      })

      if (rememberMe.value) {
        localStorage.setItem('remember_username', loginForm.username)
      } else {
        localStorage.removeItem('remember_username')
      }

      ElMessage.success('登录成功！欢迎进入运营管理系统')
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.push(redirect)
    } catch (e: any) {
      // 错误信息已在 Axios 拦截器中提示
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped lang="scss">
.login-container {
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #001529 0%, #003a70 100%);
  padding: 20px;
}

.login-box {
  width: 900px;
  height: 520px;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.25);
  display: flex;
  overflow: hidden;
}

.login-left {
  flex: 1;
  background: linear-gradient(135deg, #1890ff 0%, #096dd9 100%);
  color: #ffffff;
  padding: 40px;
  display: flex;
  align-items: center;

  .brand-content {
    .brand-icon {
      font-size: 48px;
      margin-bottom: 16px;
      color: #e6f7ff;
    }
    .brand-title {
      font-size: 28px;
      font-weight: bold;
      margin-bottom: 12px;
      letter-spacing: 1px;
    }
    .brand-desc {
      font-size: 14px;
      color: #e6f7ff;
      line-height: 1.6;
      margin-bottom: 32px;
    }

    .brand-features {
      display: flex;
      flex-direction: column;
      gap: 16px;

      .feature-item {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 14px;
        background: rgba(255, 255, 255, 0.12);
        padding: 10px 14px;
        border-radius: 6px;
      }
    }
  }
}

.login-right {
  flex: 1;
  padding: 40px 48px;
  display: flex;
  align-items: center;

  .form-wrapper {
    width: 100%;

    .form-title {
      font-size: 22px;
      font-weight: 600;
      color: #303133;
      margin-bottom: 6px;
    }
    .form-subtitle {
      font-size: 13px;
      color: #909399;
      margin-bottom: 28px;
    }

    .remember-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;

      .tip-text {
        font-size: 12px;
        color: #909399;
      }
    }

    .submit-btn {
      width: 100%;
      height: 44px;
      font-size: 15px;
      font-weight: 500;
      letter-spacing: 2px;
    }

    .login-footer {
      margin-top: 24px;
      text-align: center;
      font-size: 12px;
      color: #bfbfbf;
    }
  }
}
</style>
