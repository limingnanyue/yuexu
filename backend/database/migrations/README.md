# 数据库迁移

脚手架阶段使用 `Base.metadata.create_all()` 自动建表，满足本地 SQLite 个人部署。

后续接入 Alembic 时，在本目录初始化迁移环境：

```bash
# 在 backend 目录下执行
alembic init database/migrations
alembic revision --autogenerate -m "init schema"
alembic upgrade head
```

注意事项：

1. 迁移脚本中不要写入任何密钥、账号数据；
2. 生产环境（PostgreSQL）建议关闭 `create_all`，统一走迁移；
3. 迁移文件随源码提交，本地数据库文件（`data/*.db`）已被 `.gitignore` 忽略。
