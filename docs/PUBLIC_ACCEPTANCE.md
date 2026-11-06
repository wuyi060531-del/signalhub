# 源码展示候选验收

2026-11-06，Asia/Shanghai。此记录的输入全部为合成或测试数据，采用新建 PostgreSQL 集群、独立数据库和回环端口。依赖下载和漏洞索引查询仅使用软件包名称与版本。运行用例未启动真实岗位采集、付费 LLM 或离线翻译模型。

## 依赖和兼容性

Maven 实际解析的版本如下。使用 Spring Boot 的版本管理，Java 目标版本仍为 21。

| 组件 | 原版本 | 展示候选 |
| --- | --- | --- |
| Spring Boot | 3.5.7 | 4.1.2 |
| Spring Framework / Web MVC | 6.2.12 | 7.0.10 |
| Spring Security | 6.5.6 | 7.1.2 |
| Tomcat Embed | 10.1.48 | 11.0.27 |
| Flyway Core / PostgreSQL | 11.7.2 | 12.4.0 |
| Jackson Databind | 2.19.2 | 3.1.7 |
| PostgreSQL JDBC | 42.7.8 | 42.7.14 |

Boot 3.5 的开源维护已结束。旧 Tomcat 10.1.48 落在 HTTP/2 请求头校验通告 CVE-2026-41293 的受影响范围。候选所用 Tomcat 11.0.27 包含 11.x 的 CVE-2026-101356 等修复。Spring Security 7.1.2 高于 CVE-2026-47842 的 7.1.x 修复起点。公告中的具体受影响功能和配置以上游为准。[Spring Boot 支持公告](https://spring.io/blog/2026/06/25/spring-boot-3-5-16-available-now/) · [Boot 4.1.2 发布说明](https://github.com/spring-projects/spring-boot/releases/tag/v4.1.2) · [Tomcat 10.x 公告](https://tomcat.apache.org/security-10.html) · [Tomcat 11.x 公告](https://tomcat.apache.org/security-11.html) · [Spring Security 公告](https://spring.io/security/cve-2026-47842/)

通过 OSV 查询全部 110 个已解析 Maven 依赖坐标（含测试）及新 Python 环境中的 28 个依赖包，查询均完整返回，无通告命中。旧 Tomcat 坐标用同一接口复查有命中。结果仅覆盖当日索引和所列应用依赖。[OSV 查询文档](https://google.github.io/osv.dev/api/)

Jackson 3 保留此前 Spring Boot 的 HTTP JSON 默认行为，DTO 仍拒绝未知字段；日期保持 ISO 文本。保留默认回环监听、Host 校验、CSRF、CSP、错误消息边界。V1–V12 迁移文件逐字未改。

## 独立运行结果

环境为 macOS arm64、JDK 21.0.12.1、Maven 3.9.9、Python 3.12.14、PostgreSQL 17.6、Node 24.22.1。使用空 Maven 本地缓存和独立 Python venv，在候选目录内重新下载、安装、编译和执行。

| 实际执行 | 结果 |
| --- | --- |
| 安装 Python、`pip check`、Java 21 编译与打包 | 通过，生成可运行 JAR |
| `scripts/check.sh` | Java 93、Python 289，通过。规则与 Mock 评估和部署静态检查通过 |
| `node --test tests/*.test.cjs`、脚本语法检查 | 14 项通过，`app.js` 与 `startup.js` 语法通过 |
| `scripts/integration_smoke.py` | 26 组真实回环 HTTP 通过，包括恶意 Host、缺少 CSRF、CSP、日期和字段校验、企业归属与工作地点、逐岗在列证据、三态资格、版本和缓存 |
| `scripts/public_demo.py --verify-only` | 空库应用 V1–V12；Java 入队、Python 领取完成；重放不增版，修改产生第二份原始记录和 V2；旧分隐藏，重算 84.5；到岗资格“信息不足”；收藏和模拟投递各一条历史；译文不可用仍有英文原文；AI disabled，计费用量 0 |
| 旧库兼容性 | Boot 3.5.7 用隔离库保存合成流程后停止，Boot 4.1.2 在同一隔离库通过全部 12 项迁移校验且无需迁移。前后 API 的原文、两个版本、匹配和投递历史一致。实际监听地址为 127.0.0.1 |
| Chrome 合成页面 | 详情、投递、任务页在 1440 宽通过，详情在 390 宽通过。检查关键文本、页面横向溢出和捕获的页面 JS 异常。两张截图逐图核对为合成数据 |
| Docker / GitHub Actions | 两套 Compose 配置均通过 `docker compose config --quiet`。Docker 29.8.2 / Compose 5.5.0 实际构建在 Docker Hub 匿名授权时超时，镜像构建和容器业务烟测未完成，验收项目无容器、卷或网络残留。GitHub Actions 配置静态通过，远程 CI 尚未运行 |
| 临时资源 | Java 与 PostgreSQL 测试监听端口已释放，相关临时集群目录已清理 |

候选排除了与具体真实岗位研究脚本绑定的 6 个 Python 测试。测试数来自该目录的实际运行。含 PostgreSQL 的回归按 Java → Python → HTTP 顺序执行，配置示例见[演示导览](PUBLIC_DEMO.md)。

## 数据解释和发布范围

- 合成条目以 `is_demo` 标记，默认从真实统计和列表排除。历史存档、最近人工核验在列和个人资格分别判断，来源响应与岗位链接可访问不能替代逐岗证据。企业归属独立于工作地点。
- 春季到岗、届别、可实习时长分别核对。规则评分描述条件匹配程度，未知资格保持“信息不足”。机器译文是可选参考，原文用于证据核对。
- 公开候选仅含白名单源码、测试、迁移、配置示例、脚本和匿名合成图。验收配置中的固定值限本机测试服务，演示每次生成独立口令。发布时由所有者确定项目许可证。[第三方声明](THIRD_PARTY_NOTICES.md)
- 正式 V1.0 仍缺连续 72 小时稳定性和正式 V12 恢复证据。源码展示范围为本机单用户，无公网认证，也没有多用户压测、在招全量核验或模型研发证据。
