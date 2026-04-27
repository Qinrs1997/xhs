---
id: xhs_image_full
name: 小红书图片生成（完整版）
version: "1.1.0"
description: 完整的小红书风格图片生成提示词
variables:
  page_content:
    type: string
    required: true
    description: 页面内容
  page_type:
    type: string
    required: true
    description: 页面类型
  full_outline:
    type: string
    required: false
    description: 完整大纲
  user_topic:
    type: string
    required: false
    description: 用户主题
---
生成一张小红书风格的竖版图文图片（3:4比例，高清，适合手机屏幕）。

【合规要求】禁止出现任何平台 logo、水印、用户 ID。参考图片中如有水印请去除。

页面类型：{{ page_type }}
页面内容：
{{ page_content }}

{% if page_type != "封面" %}
风格必须与封面保持一致（参考最后一张图片的配色、排版、设计风格）。
{% endif %}

设计要求：
- 整体风格：清新精致，符合年轻人审美，配色和谐
- 文字排版：清晰可读，重要信息突出，留白合理
- 视觉元素：背景简洁不单调，可加装饰性图标/插画
- 所有文字内容必须完整呈现，竖屏排版（不可旋转或倒置）
- 直接输出图片，不要手机边框或白色留边

{% if page_type == "封面" %}封面特殊要求：标题大而醒目占据主要位置，整体有视觉冲击力{% endif %}
{% if page_type == "内容" %}内容页特殊要求：信息层次分明，列表项清晰，重点用颜色/粗体强调{% endif %}
{% if page_type == "总结" %}总结页特殊要求：总结性文字突出，有完成感和鼓励性元素{% endif %}

{% if user_topic %}用户原始需求：{{ user_topic }}{% endif %}

{% if full_outline %}
完整大纲参考（用于保持风格一致性）：
{{ full_outline }}
{% endif %}
