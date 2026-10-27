# Crawl4AI Agent

使用Crawl4AI解析网页内容，返回结构化的Markdown格式给AI

## 功能特性

- 🕷️ **智能网页爬取**: 使用Crawl4AI进行高性能网页爬取
- 📝 **Markdown输出**: 自动将网页内容转换为AI友好的Markdown格式
- 🎯 **内容选择**: 支持CSS选择器提取特定内容
- ⏱️ **智能等待**: 支持等待特定元素加载
- 🖼️ **截图功能**: 可选生成页面截图
- 🔄 **JavaScript支持**: 支持执行JavaScript获取动态内容

## 安装依赖

```bash
pip install -r requirements.txt
crawl4ai-setup
```

## 使用方法

### 基本用法

```json
{
  "tool_name": "网页解析",
  "url": "https://example.com"
}
```

### 高级用法

```json
{
  "tool_name": "网页解析",
  "url": "https://example.com",
  "css_selector": ".main-content",
  "wait_for": ".dynamic-content",
  "javascript_enabled": true,
  "screenshot": true
}
```

## 参数说明

- **url** (必需): 要解析的网页URL
- **css_selector** (可选): CSS选择器，用于提取特定内容
- **wait_for** (可选): 等待的元素选择器
- **javascript_enabled** (可选): 是否启用JavaScript执行，默认true
- **screenshot** (可选): 是否生成截图，默认false

## 配置选项

可以在config.json中配置以下参数：

```json
{
  "crawl4ai": {
    "headless": true,
    "timeout": 30000,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "viewport_width": 1280,
    "viewport_height": 720
  }
}
```

## 输出格式

Agent会返回结构化的Markdown内容，包括：

- 网页标题和描述
- 主要内容
- 媒体文件信息
- 链接列表
- 页面元数据

## 错误处理

- 如果Crawl4AI未安装，会提示用户安装
- 网络错误或解析错误会返回详细的错误信息
- 支持超时设置和重试机制

## 示例输出

```markdown
# 网页解析结果

**URL**: https://example.com

**标题**: Example Domain

**描述**: This domain is for use in illustrative examples in documents.

---

## 内容

# Example Domain

This domain is for use in illustrative examples in documents. You may use this
domain in literature without prior coordination or asking for permission.

## 媒体文件

共发现 0 个媒体文件

## 链接

共发现 0 个链接
```