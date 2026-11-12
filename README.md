# 微信聊天备份查看器

独立发行项目 —— 微信 7.0.17 聊天记录浏览器（只读）。

## 目录结构

项目目录只放代码；数据在 `/data/filebrowser/files/father/wechat/`（数据区）：

```
wechat-viewer/                                # 项目（纯代码）
├── app.py               # 服务: python app.py -> http://127.0.0.1:8010
├── import_standard.py   # 重新导入(可选): decrypted.db -> standard.db
├── static/htmx.min.js
├── start.sh             # Linux 一键拉起(装成 systemd user 服务, 常驻)
├── stop.sh              # Linux 停止服务
├── wechat-viewer.service# systemd user unit
├── start.bat            # Windows 一键启动
├── README.md
└── .gitignore           # 排除数据产物(standard.db/media/server.log)

/data/filebrowser/files/father/wechat/   # 数据区（不入 git）
├── standard.db          # 已导入的标准结构库(会话/消息/媒体路径)
├── wechat_media/        # 微信媒体原件(4.0GB, 9 个子目录)
├── decrypted.db         # EnMicroMsg.db 明文(重导源)
├── decrypted_view.db    # 真全库只读视图
└── decrypted/ ...       # 其他聊天记录产物
```

服务读的是 `standard.db` 与 `wechat_media`（绝对路径，见 `config.json`），项目内不含数据。
端口默认 **8010**，可用环境变量 `WECHAT_PORT` 覆盖。


## 启动

### Linux（常驻，推荐）

```
./start.sh     # 装成 systemd user 服务并拉起, 注销/重启/崩溃自动恢复
./stop.sh      # 停止
```

浏览器打开 <http://127.0.0.1:8010>。日志：`journalctl --user -u wechat-viewer -n 30 --no-pager`

### Windows

双击 `start.bat`，或手动 `python app.py`。

### 手动（任意平台）

```
python app.py                   # 默认 8010
WECHAT_PORT=9000 python app.py  # 换端口
```

## 功能

- 左侧会话列表（可搜索）；右侧消息流（图片 / 语音 / 视频 / 表情 / 链接 / 文字）
- **滚动加载**：进入会话自动滚到最新；滚动到顶部加载更早消息（50 条/页），到底自动停止
- 媒体：`wechat_media`（`image2/` 原图、`voice2/` 语音、`video/` 视频、`emoji/` 表情）
- 消息按 5 分钟分组显示时间戳；群消息显示发送者昵称

## 重新导入（可选）

数据源 `standard.db` 已就绪，一般不用重导。若需重建：

```
python import_standard.py   # 从 /data/filebrowser/files/father/wechat/decrypted.db 重建
```

- 图片 lightbox（点击放大/左右切换/缩放/拖拽/键盘）、视频点击全屏播放
