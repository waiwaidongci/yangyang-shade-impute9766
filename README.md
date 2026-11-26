# 苗圃遮阳台传感器缺测补记

河桥苗圃有 12 名育苗与移栽工作人员，使用两种开孔率的遮阳网台架。轮换探头时，温度、湿度或光照读数可能漏录。种植员在排移栽班前需要知道哪些读数有参考值，哪些仍需回台补测。

## 启动与登录

```sh
cp .env.example .env
docker compose build backend
docker compose up -d --no-build --wait
curl -fsS http://127.0.0.1:19439/api/health
curl -fsS http://127.0.0.1:19439/api/spec
```

Python 3.11 FastAPI 处理请求，MySQL 8.0 保存批次、运行、签核与审计，Redis 唤醒后台 worker。数据库只绑定本机 `17939`。启动时默认加载合成数据，可通过 `SEED_DEMO=false` 停用，也可手动运行 `docker compose exec -T backend python -m scripts.seed_demo`。

| 演示账号 | 密码 | 操作 |
|---|---|---|
| `analyst@demo.local` | `Demo-2611!` | 导入读数、试算参数、检查插补或拒补原因 |
| `admin@demo.local` | `Demo-2611!` | 查阅审计记录、签核交接单 |
| `viewer@demo.local` | `Demo-2611!` | 查看台账与获批结果、下载 CSV |

使用 `POST /api/auth/login` 获取令牌，随后发送 `Authorization: Bearer <token>`。CSV 完整列名见 `GET /api/spec`，OpenAPI 见 `/api/openapi.json`。CSV 简例仅说明格式，正式运行还需要足够的训练和留出记录。

```csv
reading_id,batch_id,partition,shade_class,temp_c,rh_pct,par
TR-01-01,TR-01,train,mesh30,19.4,78.3,128.2
HO-01-01,HO-01,holdout,mesh30,19.7,77.9,133.1
PE-01-01,PE-01,pending,mesh30,19.8,78.1,
```

1. `GET /api/datasets` 获取演示台账，或 `POST /api/datasets` 提交 `{"name":"移栽测次","csv":"…"}`。
2. `POST /api/runs` 提交 `{"label":"二号遮阳台上午补测","dataset_id":1,"settings":{}}`，记录返回的运行 ID。
3. `GET /api/runs/{id}` 查看覆盖率、每个字段的留出 MAE 及建议值。
4. 复核员通过 `POST /api/runs/{id}/review` 提交 `{"decision":"approved","note":"已核对补测清单"}`。
5. 从 `GET /api/runs/{id}/export/missing_cells` 下载交班表。字段误差、遮挡明细和冻结尺度各有独立导出表。

## 计算与数据范围

同档训练读数的标准差用于缩放目标字段之外的有效已测列。算法取标准化均方根距离最小的 `neighbors` 条记录，按距离倒数加权。如果有零距离记录，就取所有零距离供体的均值。可用字段数低于 `min_anchors` 或同档记录不足时，导出人工补测原因。`mask_seed` 决定留出批遮挡顺序。每行隐藏一个字段，KNN 与同档训练中位数在相同可估单元上按字段对比 MAE。单列随机遮挡的覆盖率只适用于此回测设定。

数据要按 `train`、`holdout`、`pending` 整批分区，定义在 `backend/src/domain/settings.py`，并由 `records.py` 校验。`Role`、`RunStatus` 和 `Decision` 定义于 `backend/src/constants/workflow.py`，用于鉴权、worker 状态与签核接口。业务代码位于 `backend/src/domain`，应用层位于 `backend/src/{routes,services,models,schemas}`，数据库初始化与 seed 位于 `backend/migrations`、`backend/scripts`。`.env.example` 包含端口、签名密钥及演示数据开关。

第三方依赖采用各自的许可证。
