---
id: xhs_image_short
name: 小红书图片生成（简版）
version: "1.1.0"
description: 简短的小红书风格图片提示词
variables:
  page_content:
    type: string
    required: true
    description: 页面内容
  page_type:
    type: string
    required: true
    description: 页面类型
---
生成小红书风格竖版图片（3:4比例，高清）。

页面类型：{{ page_type }}
页面内容：{{ page_content }}

要求：清新精致、文字清晰可读、排版美观、无 logo 水印。所有文字完整呈现，竖屏排版。
{% if page_type == "封面" %}封面标题大而醒目，有视觉冲击力。{% endif %}
