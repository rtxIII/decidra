"""Decidra cron 任务注册表：所有周期任务的唯一注册入口。

用法::

    python -m decidra.tasks install   # 按注册表同步全部 cron job（含清理失效 job）
    python -m decidra.tasks list      # 查看已注册的 decidra 任务

任务集合由 ``registry.build_jobs()`` 声明式产出（当前为每个启用策略一个独立
job，独立 schedule）；新增周期任务（数据预取、报表等）在 registry 中追加即可，
不必新建 install 入口。``decidra_`` 前缀的 job 归本注册表所有：install 时不在
注册表中的同前缀 job 会被删除。
"""
