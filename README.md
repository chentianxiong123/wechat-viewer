# 微信聊天备份查看器

独立发行项目 —— 微信 7.0.17 聊天记录浏览器（只读）。

## 目录结构

```
wechat-viewer/
├── app.py               # 服务: python app.py -> http://127.0.0.1:8000
├── import_standard.py   # 重新导入(可选): decrypted.db -> standard.db
├── standard.db          # 已导入的标准结构库(会话/消息/媒体路径)
├── media/               # 微信媒体(junction -> C:/Users/a1/wechat_media)
├── static/htmx.min.js
├── start.bat            # 一键启动
└── README.md
```

## 启动

双击 `start.bat`，或手动：

```
python app.py
```

浏览器打开 <http://127.0.0.1:8000>。

## 功能

- 左侧会话列表（可搜索）；右侧消息流（图片 / 语音 / 视频 / 表情 / 链接 / 文字）
- **滚动加载**：进入会话自动滚到最新；滚动到顶部加载更早消息（50 条/页），到底自动停止
- 媒体：`media/` 目录（`image2/` 原图、`voice2/` 语音、`video/` 视频、`emoji/` 表情）
- 消息按 5 分钟分组显示时间戳；群消息显示发送者昵称

## 重新导入（可选）

数据源 `standard.db` 已就绪，一般不用重导。若需重建：

```
python import_standard.py   # 从 C:/Users/a1/Documents/HiSuite/decrypted.db 重建
```

`media/` 是 junction，指向 `C:/Users/a1/Documents/HiSuite/wechat_media`（4.0GB 媒体原件）。
