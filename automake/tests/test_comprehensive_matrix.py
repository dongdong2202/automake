"""
AutoMake 智能制造系统 · 客观不变量与全场景模糊测试用例套件
(Django Standard Test Case Integration)
"""

from django.test import TransactionTestCase
from tests.test_independent_chaos_oracle import (
    FuzzEnvironment,
    IndependentShadowLedger,
    IndependentChaosRunner,
    BlackBoxInvariantAuditor
)


class ComprehensiveIndependentOracleTestCase(TransactionTestCase):
    """
    黑盒反向验证与全景模糊测试套件：
    不依赖业务自身逻辑进行逻辑断言，完全基于随机输入与外部客观物理不变量（质量守恒、零超卖、幂等性、熔断屏障）。
    """
    reset_sequences = True

    def test_randomized_chaos_and_invariant_audit(self):
        """执行 100 轮随机并发事务与全量客观不变量反向核验"""
        device_sn = "SN_DJANGO_ORACLE_01"
        env = FuzzEnvironment(device_sn)
        init_consumables, init_barrels = env.setup_random_topology()

        ledger = IndependentShadowLedger(init_consumables, init_barrels)
        runner = IndependentChaosRunner(
            env=env,
            ledger=ledger,
            scale=80,
            concurrency=8,
            with_chaos=True
        )

        success = runner.run()
        self.assertTrue(success, "独立模糊测试六大物理不变量反向对账失败，存在守恒差额或超卖漏洞！")
