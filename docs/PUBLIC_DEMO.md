# 合成演示导览

从 [README](../README.md) 安装工具和依赖、构建 JAR，再执行：

```sh
.venv/bin/python scripts/public_demo.py
# 只跑断言和清理：
.venv/bin/python scripts/public_demo.py --verify-only
```

- 演示只绑定 `127.0.0.1:18085`；数据库只绑定 `127.0.0.1:55435`，库名固定为 `signalhub_demo_test`。端口占用时退出。脚本新建私有临时目录、随机密码和 SCRAM 集群，验证数据目录、应用 PID、库名与 V1–V12。演示不读取仓库 `.env`、正式数据库、个人档案或本地翻译模型。停止后回收本次临时目录；异常中断时不要停止占用该端口的陌生进程。
- 第一次由 Java HTTP API 入队，独立 Python 进程运行一次 Worker tick；重复导入命中幂等；修改正文生成第二个原始记录和 V2。任务页可检查结果，详情可对比历史版本。演示用逐次 tick 处理已知任务；展示期间没有常驻采集调度，后来提交的任务不会自动执行。
- 详情可看 84.5 分、两版原文与“春季到岗待核验”。在“投递记录”查看合成 JD 的收藏与“已投递”记录；这只是模拟状态，没有任何外部投递。
- 未安装离线模型时，翻译接口返回 unavailable，详情保留英文原文。付费 AI 队列返回 disabled、用量为 0。合成岗位标记为演示，默认真实列表/统计排除。演示不适用真实招聘结论。
- 两张截图来自本机隔离合成环境；无用户档案、真实岗位、浏览器账户、机器路径或密钥。

CI 的 PostgreSQL 服务用于隔离回归，演示库不复用它。手动回归时，将 `TEST_DB_URL` 与 `TEST_DATABASE_URL` 指向同一个新建本机 `_test` 库，分别用 JDBC/SQLAlchemy 格式并配置 `TEST_DB_USER`、`TEST_DB_PASSWORD`；按 Maven verify → pytest → HTTP smoke 顺序运行。测试会清理目标测试库里的测试数据，不在演示运行时与其共享实例。
