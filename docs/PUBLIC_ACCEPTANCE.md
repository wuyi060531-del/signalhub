# 验收记录

这里记录实际跑过的检查和结果。输入全部是合成或测试数据，使用新建的 PostgreSQL 集群、独立数据库和回环端口。依赖下载和漏洞索引查询只用到了软件包的名称和版本。测试过程中没有启动真实的岗位采集、付费 LLM 或离线翻译模型。

## Worker 租约修复基线的 CI

基线提交 `84edc18` 的 [GitHub Actions](https://github.com/wuyi060531-del/signalhub/actions/runs/42326750779) 成功，包含两个任务：

- `test`：Python 293 项测试通过，另有 26 组真实回环 HTTP 集成检查通过。
- `container-test`：容器构建和运行检查通过。

这次提交修复了 Worker 的写入隔离：入库写入前会锁定任务行并检查租约，租约丢失时返回 `superseded`，旧 Worker 不会再覆盖新的结果（`pipeline.py` 的 `TaskLease`，`test_pipeline.py` 新增了对应的测试）。

## PR #1 本机验收（2026-11-07）

macOS arm64、Temurin 21.0.12.1、Maven 3.9.9、Python 3.12.14、Node 24.22.1、PostgreSQL 17.6、Chrome 156。Java、Python 和 HTTP 检查依次使用新建的 `signalhub_pr1_test`（PostgreSQL 55468，HTTP 18086）；演示另建 `signalhub_demo_test`（PostgreSQL 55435，HTTP 18085）。只监听 `127.0.0.1`，使用临时凭据和合成数据；没有加载正式环境配置，也没有访问外部招聘服务、真实 AI 或翻译服务。

| 命令 | 本机实测结果 |
| --- | --- |
| `bash scripts/check.sh` | Java 93 项、Python 293 项通过，0 失败/跳过；12 个规则/Mock 评估样本和 6 项部署静态检查执行完毕。Mock 的类别与相关性各有 1 个误判；未调用真实模型 |
| `node --test tests/*.test.cjs` | 17 通过，0 失败/跳过 |
| `bash scripts/mvn.sh -o -B -ntp -f backend-java/pom.xml -DskipTests package` | 打包成功；测试由上面的检查单独执行 |
| `python scripts/integration_smoke.py` | 26 组真实 HTTP 检查通过，0 失败/跳过；含合成投递历史及禁用 AI 的降级 |
| `python scripts/public_demo.py --verify-only` | 1 次完整演示通过，0 失败/跳过：Flyway V1–V12、导入去重、V2 与旧分失效、重算 84.5、资格信息不足、两步本地投递历史；AI 为 disabled、翻译为 unavailable |
| Chrome 390×844 | 国内岗位、外企岗位、岗位详情、数据源与任务、收藏与投递共 5 页通过；每页 `scrollWidth / clientWidth` 都是 390 / 390，未出现未处理 JS 异常 |

国内与外企列表用真实导入队列各补入一条虚构岗位，通过本机 API 录入虚构企业分类，实际核对两类列表都能显示相应合成岗位。修复前两页的筛选控件使整页宽度达到 404px；修复仅允许窄屏的岗位筛选控件在网格内收缩。详情、任务和投递页面也在修复后重测。

[匹配截图](demo-assets/matching.png)和[投递截图](demo-assets/applications.png)都在 1380×900 的临时 Chrome 会话中从真实演示后端拍摄。匹配表的到岗窗口按日期分隔，来源未知时显示“未明确”；投递看板显示虚构岗位的“已收藏”和“已投递”，都是本地状态。截图不含个人账号、私人档案或本机路径。未重跑本机 Docker 或真机浏览器。

## 依赖与兼容性

Maven 实际解析的版本（Java 目标版本仍是 21）：

| 组件 | 原版本 | 现版本 |
| --- | --- | --- |
| Spring Boot | 3.5.7 | 4.1.2 |
| Spring Framework / Web MVC | 6.2.12 | 7.0.10 |
| Spring Security | 6.5.6 | 7.1.2 |
| Tomcat Embed | 10.1.48 | 11.0.27 |
| Flyway Core / PostgreSQL | 11.7.2 | 12.4.0 |
| Jackson Databind | 2.19.2 | 3.1.7 |
| PostgreSQL JDBC | 42.7.8 | 42.7.14 |

Boot 3.5 的开源维护已经结束，旧的 Tomcat 10.1.48 落在 HTTP/2 请求头校验通告 CVE-2026-41293 的影响范围内。现在的 Tomcat 11.0.27 包含 11.x 对 CVE-2026-101356 等的修复，Spring Security 7.1.2 高于 CVE-2026-47842 的 7.1.x 修复起点。具体影响的功能和配置以上游公告为准：[Spring Boot 支持公告](https://spring.io/blog/2026/06/25/spring-boot-3-5-16-available-now/) · [Boot 4.1.2 发布说明](https://github.com/spring-projects/spring-boot/releases/tag/v4.1.2) · [Tomcat 10.x 公告](https://tomcat.apache.org/security-10.html) · [Tomcat 11.x 公告](https://tomcat.apache.org/security-11.html) · [Spring Security 公告](https://spring.io/security/cve-2026-47842/)

对全部 110 个解析出的 Maven 依赖（含测试）和新 Python 环境里的 28 个依赖包做了 OSV 查询，查询都完整返回，没有命中通告；用同一接口复查旧的 Tomcat 坐标则有命中。结果只覆盖当天的索引和所列的应用依赖。[OSV 文档](https://google.github.io/osv.dev/api/)

Jackson 3 保留了此前的 HTTP JSON 默认行为：DTO 仍然拒绝未知字段，日期保持 ISO 文本。默认回环监听、Host 校验、CSRF、CSP 和错误消息边界都没有变，V1–V12 迁移文件没有改动。

## 独立运行结果（2026-11-06）

环境：macOS arm64、JDK 21.0.12.1、Maven 3.9.9、Python 3.12.14、PostgreSQL 17.6、Node 24.22.1。使用空的 Maven 本地缓存和独立的 Python 虚拟环境，在项目目录内重新下载、安装、编译并执行。

| 检查 | 结果 |
| --- | --- |
| 安装 Python 依赖、`pip check`、Java 21 编译打包 | 通过，生成可运行的 JAR |
| `scripts/check.sh` | Java 93 项、Python 289 项通过，规则与 Mock 评估、部署静态检查通过 |
| `node --test tests/*.test.cjs`、脚本语法检查 | 14 项通过，`app.js` 和 `startup.js` 语法正确 |
| `scripts/integration_smoke.py` | 26 组真实回环 HTTP 检查通过：恶意 Host、缺少 CSRF、CSP、日期和字段校验、企业归属与工作地点、逐岗在列证据、三态资格、版本和缓存 |
| `scripts/public_demo.py --verify-only` | 空库应用 V1–V12；Java 入队、Python 领取并完成；重放不增加版本，修改后产生第二份原始记录和 V2；旧分隐藏，重算得 84.5；到岗资格为“信息不足”；收藏和模拟投递各有一条历史；译文不可用时仍有英文原文；AI 为 disabled，计费用量 0 |
| 旧库兼容 | 用 Boot 3.5.7 在隔离库里保存一次合成流程后停止，Boot 4.1.2 在同一个库上通过全部 12 项迁移校验，不需要迁移；前后 API 返回的原文、两个版本、匹配和投递历史一致，监听地址是 127.0.0.1 |
| Chrome 页面检查 | 详情、投递、任务页在 1440 宽通过，详情页在 390 宽通过。检查了关键文本、页面是否横向溢出、是否有页面 JS 异常；两张截图逐张确认是合成数据 |
| Docker 与 Compose | 两套 Compose 配置都通过 `docker compose config --quiet`。本地 Docker 构建当时因 Docker Hub 匿名授权超时没有完成，容器烟测在 GitHub Actions 里通过（见上） |
| 临时资源 | Java 和 PostgreSQL 的测试端口已释放，临时集群目录已清理 |

仓库里没有包含 6 个与具体真实岗位的研究脚本绑定的 Python 测试。含 PostgreSQL 的回归按 Java → Python → HTTP 的顺序执行，配置示例见[演示说明](PUBLIC_DEMO.md)。

## 数据口径与发布范围

- 合成条目带有 `is_demo` 标记，默认不进入真实的统计和列表。“历史存档”“最近一次人工核验仍在招”“个人资格”分别判断；来源接口能访问、岗位链接能打开，都不能代替逐岗的证据。企业归属和工作地点各自独立。
- 春季到岗、届别、可实习时长分别核对。规则评分只表示条件的匹配程度，未知的资格保持“信息不足”。机器翻译只是可选的参考，核对证据以原文为准。
- 仓库里只有白名单内的源码、测试、迁移、配置示例、脚本和匿名的合成截图。验收配置里的固定值只用于本机测试服务，演示每次都会生成独立口令。第三方声明见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。

## 还没有做的验证

- V1.0 要求的连续 72 小时稳定性，以及正式环境的 V12 恢复，都没有验证。
- 范围是本机单用户，没有公网认证，没有多用户压测，没有对在招岗位做全量核验，也没有模型研发方面的证据。
