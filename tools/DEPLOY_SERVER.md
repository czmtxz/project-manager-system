# 部署到生产服务器 (36.212.73.151:888)

目标目录：`/opt/project_manager/project_manager/`

## 自动部署（推荐）

代码改动后会自动尝试部署，无需每次手动执行：

1. **Cursor Agent**：项目已配置 `.cursor/hooks.json`，每轮对话结束（`stop`）时运行 `tools/deploy_to_server.ps1`。日志：`.cursor/deploy-last.log`
2. **Agent 规则**：`.cursor/rules/auto-deploy-production.mdc` 要求助手在改完业务代码后执行部署脚本
3. **Git 提交（可选）**：`powershell -File tools/install-git-deploy-hook.ps1` 安装 post-commit 钩子

前提：项目根目录存在 `.ssh_deploy_key`（勿提交 Git），或设置 `$env:DEPLOY_SSH_KEY`。

手动立即部署：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\deploy_to_server.ps1
```

静默模式（钩子用）：加参数 `-Quiet`。

## 方式一：自动脚本（需 SSH 私钥）

1. 将部署私钥放到项目根目录 `.ssh_deploy_key`，或设置环境变量：
   ```powershell
   $env:DEPLOY_SSH_KEY = "C:\path\to\your_private_key"
   ```
2. 在项目目录执行：
   ```powershell
   cd "C:\Users\User\Desktop\项目管理系统"
   powershell -ExecutionPolicy Bypass -File .\tools\deploy_to_server.ps1
   ```

## 方式二：手动 SCP

```powershell
$KEY = "C:\path\to\private_key"
$SRV = "root@36.212.73.151"
$R = "/opt/project_manager/project_manager"

scp -i $KEY app.py auth_utils.py client_portal_utils.py route_extensions.py ocr_utils.py project_category_utils.py requirements.txt "${SRV}:${R}/"
scp -i $KEY -r templates migrations "${SRV}:${R}/"
ssh -i $KEY $SRV "mkdir -p ${R}/tools"
scp -i $KEY tools/migrate_client_customer_binding.py tools/server_post_deploy.sh "${SRV}:${R}/tools/"
scp -i $KEY migrations/client_collab_isolation.py "${SRV}:${R}/migrations/"
ssh -i $KEY $SRV "chmod +x ${R}/tools/server_post_deploy.sh && bash ${R}/tools/server_post_deploy.sh"
```

## 方式三：上传 deploy_bundle.zip

1. 使用 `tools\make_deploy_bundle.ps1` 生成 `deploy_bundle.zip`
2. 通过宝塔/面板上传到服务器并解压到 `/opt/project_manager/project_manager/`
3. SSH 执行：`bash /opt/project_manager/project_manager/tools/server_post_deploy.sh`

## 本次更新包含

- 客户协同账号隔离（`auth_utils.py`、`client_portal_utils.py`）
- 账号管理双 Tab、客户协同专员角色 `client_collab`
- 客户门户按 `customer_id` 数据隔离
- 数据库迁移（`customer_id` 回填、门户表）

## 验证

- 管理端：http://36.212.73.151:888/login
- 创建「客户协同专员」→ 登录后仅见客户协同菜单
- 客户门户：http://36.212.73.151:888/portal/login

**勿将 SSH 私钥提交到 Git 或发送到聊天。**
