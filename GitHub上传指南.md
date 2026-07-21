# GitHub 上传指南

> 详细说明如何将本地项目上传到 GitHub，包含账号准备、认证方式选择、密钥配置、上传操作等完整流程。

---

## 目录

- [一、前置准备](#一前置准备)
- [二、认证方式对比](#二认证方式对比)
- [三、方式 A：Personal Access Token（推荐）](#三方式-apersonal-access-token推荐)
- [四、方式 B：SSH Key](#四方式-bssh-key)
- [五、方式 C：账号密码（已废弃）](#三方式-c账号密码已废弃)
- [六、上传项目到 GitHub](#六上传项目到-github)
- [七、常用 Git 操作](#七常用-git-操作)
- [八、常见问题](#八常见问题)

---

## 一、前置准备

### 1. 注册 GitHub 账号

访问 [https://github.com/signup](https://github.com/signup) 注册账号。

记录以下信息：
- **用户名**（username）：如 `kuaitoukuai`
- **邮箱**：如 `417139320@qq.com`
- **密码**：你的 GitHub 登录密码

### 2. 安装 Git

#### Windows
下载 [Git for Windows](https://git-scm.com/download/win) 并安装。

#### macOS
```bash
brew install git
```

#### Linux
```bash
sudo apt install git      # Debian/Ubuntu
sudo yum install git      # CentOS/RHEL
```

### 3. 配置 Git 全局信息

```bash
git config --global user.name "你的用户名"
git config --global user.email "你的邮箱"
```

示例：
```bash
git config --global user.name "kuaitoukuai"
git config --global user.email "417139320@qq.com"
```

查看当前配置：
```bash
git config --list
```

### 4. 在 GitHub 创建仓库

1. 登录 GitHub，点击右上角 `+` → `New repository`
2. 填写仓库名称（如 `mimo-v2.5-pro-ultraspeed`）
3. 选择公开（Public）或私有（Private）
4. **不要**勾选 "Add a README file"（避免首次推送冲突）
5. 点击 `Create repository`

---

## 二、认证方式对比

GitHub 从 **2021 年 8 月 13 日**起，不再支持账号密码推送代码。必须使用以下方式之一：

| 方式 | 安全性 | 便捷性 | 适用场景 |
|------|--------|--------|----------|
| **Personal Access Token (PAT)** | 中 | 高 | 个人开发、HTTPS 推送 |
| **SSH Key** | 高 | 中（需配置） | 长期开发、多仓库 |
| **GitHub CLI** | 高 | 高 | 现代化工作流 |
| ~~账号密码~~ | 低 | - | **已废弃，不可用** |

---

## 三、方式 A：Personal Access Token（推荐）

### 1. 生成 PAT

1. 登录 GitHub，点击右上角头像 → `Settings`
2. 左侧菜单最底部 → `Developer settings`
3. 选择 `Personal access tokens` → `Tokens (classic)`
4. 点击 `Generate new token` → `Generate new token (classic)`
5. 填写信息：
   - **Note**：用途说明，如 `mimo-push-token`
   - **Expiration**：有效期，建议 30 天或 90 天
   - **Select scopes**：勾选 `repo`（完整仓库访问）
6. 点击 `Generate token`
7. **立即复制 token**（格式如 `ghp_xxxxxxxxxxxx`），页面关闭后无法再查看

### 2. 使用 PAT 推送

#### 方式 1：临时使用（推荐）

```bash
git remote add origin https://github.com/用户名/仓库名.git
git push -u origin main
# 提示输入 Username 和 Password 时：
# Username: 你的GitHub用户名
# Password: 粘贴 PAT（不是账号密码！）
```

#### 方式 2：URL 中嵌入 PAT（方便但要注意安全）

```bash
git remote add origin https://用户名:ghp_xxxxx@github.com/用户名/仓库名.git
git push -u origin main
```

#### 方式 3：缓存 PAT（避免重复输入）

```bash
# 缓存 1 小时
git config --global credential.helper cache
git config --global credential.helper 'cache --timeout=3600'

# 或永久存储（明文存在 ~/.git-credentials）
git config --global credential.helper store
```

配置后首次推送输入 PAT，之后会自动使用。

### 3. 管理 PAT

- 查看/删除 PAT：`Settings` → `Developer settings` → `Personal access tokens`
- PAT 失效后重新生成，更新本地缓存：
  ```bash
  # Windows: 控制面板 → 凭据管理器 → Windows 凭据 → 找到 git:https://github.com → 删除
  # macOS:钥匙串访问 → 搜索 github.com → 删除
  ```

---

## 四、方式 B：SSH Key

### 1. 检查现有 SSH Key

```bash
ls -al ~/.ssh
# Windows: dir %USERPROFILE%\.ssh
```

如果已有 `id_ed25519.pub` 或 `id_rsa.pub`，可跳过生成步骤。

### 2. 生成新 SSH Key

```bash
ssh-keygen -t ed25519 -C "你的邮箱"
# 示例：ssh-keygen -t ed25519 -C "417139320@qq.com"
```

按提示操作：
- **保存位置**：直接回车用默认位置（`~/.ssh/id_ed25519`）
- ** passphrase**：可留空（方便）或设置密码（更安全）

### 3. 添加 SSH Key 到 ssh-agent

```bash
eval "$(ssh-agent -s)"    # Linux/macOS
# Windows PowerShell: Start-Service ssh-agent

ssh-add ~/.ssh/id_ed25519
```

### 4. 添加 SSH Key 到 GitHub

```bash
cat ~/.ssh/id_ed25519.pub
# 复制输出内容
```

或 Windows：
```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | Set-Clipboard
```

然后：
1. 登录 GitHub → `Settings` → `SSH and GPG keys`
2. 点击 `New SSH key`
3. **Title**：如 `My Laptop`
4. **Key type**：`Authentication Key`
5. **Key**：粘贴公钥内容
6. 点击 `Add SSH key`

### 5. 测试 SSH 连接

```bash
ssh -T git@github.com
# 成功会显示：Hi 用户名! You've successfully authenticated...
```

### 6. 使用 SSH 推送

```bash
git remote add origin git@github.com:用户名/仓库名.git
git push -u origin main
```

---

## 五、方式 C：GitHub CLI（现代化）

### 1. 安装 GitHub CLI

- **Windows**：`winget install GitHub.cli`
- **macOS**：`brew install gh`
- **Linux**：参考 [官方文档](https://github.com/cli/cli#installation)

### 2. 登录

```bash
gh auth login
```

按提示选择：
- GitHub.com
- HTTPS 或 SSH
- 浏览器登录或粘贴 token

### 3. 使用

```bash
gh repo create 用户名/仓库名 --public --source=. --push
```

---

## 六、上传项目到 GitHub

### 1. 在项目目录初始化 Git

```bash
cd /path/to/your/project
git init -b main
```

### 2. 创建 .gitignore（推荐）

避免提交不必要的文件：

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# 敏感文件
.env
*.key
*.pem
credentials.json
```

### 3. 添加文件并提交

```bash
git add .
git status              # 检查将要提交的文件
git commit -m "Initial commit: 项目说明"
```

### 4. 关联远程仓库并推送

```bash
# 使用 PAT（HTTPS）
git remote add origin https://github.com/用户名/仓库名.git
git push -u origin main

# 或使用 SSH
git remote add origin git@github.com:用户名/仓库名.git
git push -u origin main
```

首次推送会要求认证（按上面选择的方式处理）。

### 5. 验证推送

访问 `https://github.com/用户名/仓库名` 查看代码。

---

## 七、常用 Git 操作

### 后续更新代码

```bash
git add 修改的文件
git commit -m "修复: 说明"
git push
```

### 拉取远程更新

```bash
git pull origin main
```

### 查看远程仓库

```bash
git remote -v
```

### 修改远程仓库地址

```bash
git remote set-url origin 新地址
```

### 删除远程仓库

```bash
git remote remove origin
```

### 查看提交历史

```bash
git log --oneline -10
```

---

## 八、常见问题

### Q1: `fatal: Authentication failed`

**原因**：密码错误或用了账号密码而非 PAT。

**解决**：
1. 确认使用 PAT 而非账号密码
2. 清除缓存的旧凭据：
   - Windows：控制面板 → 凭据管理器 → 删除 `git:https://github.com`
   - macOS：钥匙串 → 搜索 github.com → 删除
3. 重新推送，输入正确的 PAT

### Q2: `fatal: refusing to merge unrelated histories`

**原因**：本地和远程都有提交但无共同历史。

**解决**：
```bash
git pull origin main --allow-unrelated-histories
git push -u origin main
```

### Q3: `! [rejected] main -> main (fetch first)`

**原因**：远程有本地没有的更新。

**解决**：
```bash
git pull --rebase origin main
git push
```

### Q4: `Permission denied (publickey)`

**原因**：SSH key 未配置或未添加到 GitHub。

**解决**：
1. 检查 SSH key 是否存在：`ls ~/.ssh/`
2. 检查 ssh-agent 是否运行：`ssh-add -l`
3. 检查公钥是否添加到 GitHub：`Settings` → `SSH and GPG keys`
4. 测试连接：`ssh -T git@github.com`

### Q5: PAT 失效后怎么办

1. 重新生成 PAT：`Settings` → `Developer settings` → `Personal access tokens`
2. 清除旧凭据（见 Q1）
3. 推送时输入新 PAT

### Q6: 如何查看当前使用的认证方式

```bash
git config --list | grep credential
# 或查看远程 URL
git remote -v
```

URL 包含 `https://` → HTTPS + PAT
URL 包含 `git@github.com:` → SSH

### Q7: 如何切换 HTTPS 和 SSH

```bash
# SSH → HTTPS
git remote set-url origin https://github.com/用户名/仓库名.git

# HTTPS → SSH
git remote set-url origin git@github.com:用户名/仓库名.git
```

### Q8: 推送大文件失败

GitHub 单文件限制 100MB，仓库建议 1GB 以内。

```bash
# 查看大文件
git rev-list --objects --all | grep -f <(git verify-pack -v .git/objects/pack/*.idx | sort -k 3 -n | tail -10 | awk '{print $1}')

# 使用 Git LFS 处理大文件
git lfs install
git lfs track "*.psd"
git add .gitattributes
```

---

## 附录：本项目实际操作记录

本项目（mimo-v2.5-pro-ultraspeed）实际上传过程：

### 环境信息
- **GitHub 账号**：kuaitoukuai
- **邮箱**：417139320@qq.com
- **仓库**：kuaitoukuai/mimo-v2.5-pro-ultraspeed
- **认证方式**：PAT（HTTPS）

### 操作步骤

```bash
# 1. 准备项目目录
mkdir mimo_github_repo
cd mimo_github_repo
# 复制 openai_api.py, openai_api_技术文档.md, requirements.txt 到此目录

# 2. 初始化 Git
git init -b main
git config user.name "kuaitoukuai"
git config user.email "417139320@qq.com"

# 3. 添加并提交
git add openai_api.py openai_api_技术文档.md requirements.txt
git commit -m "Initial commit: MiMo v2.5-pro-ultraspeed OpenAI-compatible API"

# 4. 关联远程仓库（PAT 嵌入 URL）
git remote add origin https://kuaitoukuai:ghp_xxxxx@github.com/kuaitoukuai/mimo-v2.5-pro-ultraspeed.git

# 5. 推送
git push -u origin main

# 6. 移除 URL 中的 PAT（安全）
git remote set-url origin https://github.com/kuaitoukuai/mimo-v2.5-pro-ultraspeed.git
```

### 通过 API 上传文件（网络不稳定时的备选方案）

当 `git push` 因网络问题失败时，可通过 GitHub API 直接上传文件：

```python
import requests, base64

pat = 'ghp_xxxxx'
owner = 'kuaitoukuai'
repo = 'mimo-v2.5-pro-ultraspeed'
headers = {
    'Authorization': 'token ' + pat,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28'
}

# 读取文件内容并 base64 编码
with open('README.md', 'rb') as f:
    content = base64.b64encode(f.read()).decode('utf-8')

# 上传文件
payload = {
    'message': 'Add README',
    'content': content,
    'branch': 'main',
    'committer': {'name': 'kuaitoukuai', 'email': '417139320@qq.com'}
}

r = requests.put(
    f'https://api.github.com/repos/{owner}/{repo}/contents/README.md',
    headers=headers,
    json=payload,
    timeout=60
)
print(f'Upload status: {r.status_code}')
```

### 自动生成 PAT 的脚本

当本地无 PAT 时，可用账号密码登录 GitHub 网页自动生成 PAT：

```python
import re, requests

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# 1. 获取登录页 token
r = session.get('https://github.com/login', timeout=30)
token = re.search(r'name="authenticity_token" value="([^"]+)"', r.text).group(1)

# 2. 登录
login_data = {
    'authenticity_token': token,
    'login': 'kuaitoukuai',
    'password': '你的密码',
    'webauthn-support': 'supported',
    'webauthn-iuvpaa-support': 'unsupported',
    'return_to': 'https://github.com/login',
    'allow_signup': '',
    'client_id': '',
    'integration': ''
}
session.post('https://github.com/session', data=login_data, allow_redirects=True, timeout=30)

# 3. 获取 PAT 创建页 token
r = session.get('https://github.com/settings/tokens/new', timeout=30)
pat_token = re.search(
    r'id="new_oauth_access"[^>]*>.*?name="authenticity_token" value="([^"]+)"',
    r.text, re.DOTALL
).group(1)

# 4. 创建 PAT
pat_data = {
    'authenticity_token': pat_token,
    'oauth_access[description]': 'my-push-token',
    'oauth_access[default_expires_at]': '30',
    'oauth_access[scopes][]': 'repo'
}
r = session.post('https://github.com/settings/tokens', data=pat_data, allow_redirects=True, timeout=30)

# 5. 提取 PAT
pat = re.search(r'(ghp_[A-Za-z0-9]{30,})', r.text).group(1)
print(f'PAT: {pat}')
```

---

## 参考链接

- [GitHub 官方文档 - 连接 GitHub](https://docs.github.com/zh/authentication)
- [Git 官方文档](https://git-scm.com/doc)
- [GitHub CLI 文档](https://cli.github.com/manual/)
- [Creating a personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token)
- [Generating a new SSH key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent)
