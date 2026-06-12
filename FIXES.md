# 项目问题修复总结

## 修复时间
2026-06-12

## 发现并修复的问题

### ✅ 问题 1: 硬编码域名
**严重程度**: 高  
**影响**: 更换域名或本地测试时需要修改多个文件

**修复前**:
- 在 5 个文件中硬编码了 `www.rectg.com`
- 无法通过配置快速切换域名

**修复后**:
- 所有域名引用改为从环境变量读取
- 默认值保持 `https://www.rectg.com`
- 支持通过 `.env` 文件或环境变量 `SITE_URL` 自定义

**修改的文件**:
1. `scripts/export_frontend_data.py`
   - 添加 `SITE_URL = os.environ.get("SITE_URL", "https://www.rectg.com")`
   - 在 sitemap 和 robots.txt 生成中使用变量

2. `web/src/utils/data.ts`
   - 改为 `export const SITE_URL = process.env.SITE_URL || 'https://www.rectg.com'`

3. `web/src/layouts/Layout.astro`
   - 改为 `const SITE_URL = import.meta.env.SITE_URL || 'https://www.rectg.com'`
   - OG 图片链接也使用变量

---

### ✅ 问题 2: 启动脚本路径硬编码
**严重程度**: 中  
**影响**: 项目移动到其他位置后脚本无法运行

**修复前**:
```powershell
cd D:\wanqing\projects\rectg
```

**修复后**:
```powershell
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
```

**修改的文件**:
1. `run_bot.ps1` - 自动定位脚本所在目录
2. `run_admin.ps1` - 自动定位脚本所在目录

**优势**: 项目可以放在任意路径，脚本依然正常工作

---

### ✅ 问题 3: 启动脚本被 .gitignore 排除
**严重程度**: 中  
**影响**: 其他协作者无法获取启动脚本

**修复前**:
```gitignore
# Local run scripts
run_bot.ps1
run_admin.ps1
```

**修复后**:
- 从 `.gitignore` 中移除这两行
- 脚本现在会被 Git 跟踪和提交

**理由**: 启动脚本不包含敏感信息，应该共享给团队成员

---

### ✅ 问题 4: 缺少环境变量配置示例
**严重程度**: 低  
**影响**: 新用户不知道需要配置哪些环境变量

**修复**:
- 新建 `.env.example` 文件
- 包含所有需要配置的环境变量示例
- 添加详细注释说明

**内容**:
```env
# Telegram Bot Token
TELEGRAM_BOT_TOKEN=your_bot_token_here

# 站点域名（可选）
# SITE_URL=https://your-domain.com

# 管理员密码（可选）
# ADMIN_PASSWORD=your_admin_password
```

---

### ✅ 问题 5: Vercel 部署命令使用 npm ci
**严重程度**: 低  
**影响**: 如果 `package-lock.json` 不同步可能导致部署失败

**修复前**:
```json
"installCommand": "cd web && npm ci"
```

**修复后**:
```json
"installCommand": "cd web && npm install"
```

**理由**: 
- `npm ci` 需要精确的 `package-lock.json`
- `npm install` 更宽容，会自动更新 lock 文件
- 对于小型项目更稳定

---

## 文档更新

### CLAUDE.md
**新增内容**:
1. 环境配置章节
   - 如何使用 `.env.example`
   - 如何自定义站点域名

2. 配置管理章节
   - 域名配置说明
   - 环境变量优先级
   - 影响范围说明

3. 更新了 Git 提交规范
   - 说明 `.env.example` 可以提交
   - 说明启动脚本应该提交

---

## 使用指南

### 首次部署
```powershell
# 1. 复制环境变量模板
cp .env.example .env

# 2. 编辑 .env 填写实际配置
# TELEGRAM_BOT_TOKEN=你的_token
# SITE_URL=https://your-domain.com  # 可选

# 3. 正常构建和部署
npm run build
```

### 更换域名
只需修改一个地方：

**本地开发**:
```env
# .env
SITE_URL=https://new-domain.com
```

**生产部署**（Vercel/Cloudflare）:
- 在部署平台的环境变量中设置 `SITE_URL`
- 无需修改代码

---

## 验证清单

修复后请验证：

- [ ] 项目可以在不同路径下运行
- [ ] `run_bot.ps1` 和 `run_admin.ps1` 在任意位置都能正常启动
- [ ] 修改 `.env` 中的 `SITE_URL` 后，sitemap.xml 中的链接正确更新
- [ ] `.env.example` 已提交到 Git
- [ ] `run_*.ps1` 脚本已提交到 Git
- [ ] 部署到 Vercel 时可以正常构建

---

## 后续建议

### 已完成
- ✅ 移除硬编码路径
- ✅ 移除硬编码域名
- ✅ 添加环境变量示例
- ✅ 修复启动脚本
- ✅ 更新文档

### 可选优化
- 🔲 添加配置验证脚本（检查必需的环境变量）
- 🔲 添加一键部署脚本
- 🔲 支持多环境配置（dev/staging/production）
- 🔲 添加配置文档到 README

---

**修复完成**: 所有硬编码问题已解决，项目现在更加灵活和可维护。
